#!/usr/bin/env python3
"""Run one allow-listed ForestBridge task through the verified Jetson pipeline.

This module deliberately does not accept a shell command from the relay.  A
server-owned preset is checked against a second, Jetson-local allow-list and is
then mapped to a fixed argv vector.  Physical execution additionally consumes
a short-lived, one-shot arming lease created by an onsite operator.
"""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from forestbridge_task_executive import EventWriter, Outcome, TaskState


ARM_SCHEMA = "forestbridge/web-motion-arm/v1"
ARM_TOKEN = "FORESTBRIDGE_WEB_DEMO_ARMED"


@dataclass(frozen=True)
class LocalPreset:
    name: str
    task_type: str
    map_database: str
    goal_x_m: float
    goal_y_m: float
    goal_yaw_deg: float
    act_steps: int
    max_path_m: float = 1.20
    max_runtime_s: float = 80.0
    max_tracked_travel_m: float = 1.35
    execution_kind: str = "nav_then_act"
    hardware_enabled: bool = False
    disabled_reason: str = ""


LOCAL_PRESETS = {
    "table_pick_place_01": LocalPreset(
        name="table_pick_place_01",
        task_type="navigate_then_pick_place",
        map_database="/data/slam/mapping/20260830T095346Z/rtabmap.db",
        goal_x_m=0.052,
        goal_y_m=-0.357,
        goal_yaw_deg=-90.0,
        act_steps=600,
        hardware_enabled=False,
        disabled_reason=(
            "Relay still carries the August table pose, while the deployed robot now uses "
            "the September home-workspace map; revalidate and replace this preset onsite"
        ),
    ),
    "local_face_cream_rollout_01": LocalPreset(
        name="local_face_cream_rollout_01",
        task_type="local_pick_place",
        # The base is intentionally not commanded in this preset.  These
        # zeroes are structured Relay fields, not navigation coordinates.
        map_database="",
        goal_x_m=0.0,
        goal_y_m=0.0,
        goal_yaw_deg=0.0,
        act_steps=20,
        execution_kind="fixed_face_cream_rollout",
        hardware_enabled=True,
        disabled_reason="",
    ),
}


STAGE_MARKERS = (
    ("=== 1/5 RETURN WHITE ARM", TaskState.PRECHECK),
    ("=== 2/5 RETURN GEMINI", TaskState.SET_MAPPING_CAMERA),
    ("=== 3/5 NAVIGATE", TaskState.LOCALIZING),
    ("Nav2 path is ready", TaskState.PLANNING),
    ("AUTO_PIPELINE armed; MOVE", TaskState.NAVIGATING),
    ("=== 4/5 RETURN GEMINI", TaskState.SET_GRASP_CAMERA),
    ("=== 5/5 RUN SUPERVISED ACT", TaskState.GRASPING),
)


class HardwareTaskError(RuntimeError):
    """A hardware task was rejected or could not be safely completed."""


def _same_number(left: object, right: float, tolerance: float = 1e-6) -> bool:
    try:
        return abs(float(left) - right) <= tolerance
    except (TypeError, ValueError):
        return False


def validate_task(task: dict[str, object]) -> LocalPreset:
    spec = task.get("spec")
    if not isinstance(spec, dict):
        raise HardwareTaskError("relay task has no structured spec")
    preset_name = str(spec.get("preset", ""))
    preset = LOCAL_PRESETS.get(preset_name)
    if preset is None:
        raise HardwareTaskError(f"preset is not allow-listed on Jetson: {preset_name!r}")
    checks = {
        "task_type": str(spec.get("task_type", "")) == preset.task_type,
        "goal_x_m": _same_number(spec.get("goal_x_m"), preset.goal_x_m),
        "goal_y_m": _same_number(spec.get("goal_y_m"), preset.goal_y_m),
        "goal_yaw_deg": _same_number(spec.get("goal_yaw_deg"), preset.goal_yaw_deg),
        "act_steps": _same_number(spec.get("act_steps"), float(preset.act_steps)),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise HardwareTaskError(
            "relay task does not match the Jetson-local preset: " + ", ".join(failed)
        )
    return preset


def consume_arm_lease(path: Path, preset: str, now_s: float | None = None) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HardwareTaskError(
            f"onsite arming lease is missing: {path}; no hardware command was started"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HardwareTaskError(f"invalid onsite arming lease: {exc}") from exc

    current = time.time() if now_s is None else now_s
    valid = (
        isinstance(payload, dict)
        and payload.get("schema") == ARM_SCHEMA
        and payload.get("token") == ARM_TOKEN
        and payload.get("preset") == preset
        and isinstance(payload.get("expires_epoch_s"), (int, float))
        and float(payload["expires_epoch_s"]) >= current
    )
    if not valid:
        raise HardwareTaskError("onsite arming lease is expired or does not match the preset")

    # One lease authorizes one claimed task.  Consume it before starting any
    # child so a replayed web request cannot reuse the same onsite approval.
    path.unlink()


class HardwarePipelineExecutor:
    def __init__(
        self,
        repo_root: Path,
        arm_file: Path,
        output_dir: Path,
        poll_s: float = 0.25,
        interrupt_grace_s: float = 8.0,
        timeout_s: float = 240.0,
    ):
        self.repo_root = repo_root.resolve()
        self.arm_file = arm_file
        self.output_dir = output_dir
        self.poll_s = poll_s
        self.interrupt_grace_s = interrupt_grace_s
        self.timeout_s = timeout_s

    def command_for(self, task_id: str, preset: LocalPreset) -> list[str]:
        if preset.execution_kind == "fixed_face_cream_rollout":
            rollout = self.repo_root / "scripts" / "jetson_smolvla_white_rollout.sh"
            if not rollout.is_file():
                raise HardwareTaskError(f"verified local rollout is missing: {rollout}")
            return ["bash", str(rollout), "--execute", "--steps", str(preset.act_steps)]
        if preset.execution_kind != "nav_then_act":
            raise HardwareTaskError(f"unsupported local execution kind: {preset.execution_kind}")
        pipeline = self.repo_root / "scripts" / "jetson_nav_then_act_pick_place.sh"
        if not pipeline.is_file():
            raise HardwareTaskError(f"verified pipeline is missing: {pipeline}")
        safe_task_id = "".join(ch for ch in task_id if ch.isalnum())[:12] or "unknown"
        return [
            "bash",
            str(pipeline),
            "--auto-demo",
            "--database",
            preset.map_database,
            "--goal-x",
            str(preset.goal_x_m),
            "--goal-y",
            str(preset.goal_y_m),
            "--goal-yaw-deg",
            str(preset.goal_yaw_deg),
            "--steps",
            str(preset.act_steps),
            "--max-path-m",
            str(preset.max_path_m),
            "--max-runtime-s",
            str(preset.max_runtime_s),
            "--max-tracked-travel-m",
            str(preset.max_tracked_travel_m),
            "--label",
            f"relay_{safe_task_id}",
        ]

    def _interrupt(self, process: subprocess.Popen[bytes]) -> bool:
        if process.poll() is not None:
            return True
        os.killpg(process.pid, signal.SIGINT)
        deadline = time.monotonic() + self.interrupt_grace_s
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if process.poll() is not None:
            return True
        os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 2.0
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        return process.poll() is not None

    def run(
        self,
        task: dict[str, object],
        writer: EventWriter,
        stop_requested: Callable[[], bool],
    ) -> TaskState:
        task_id = str(task.get("task_id", ""))
        writer.emit(TaskState.PRECHECK, "task_started", mode="hardware-allowlisted")
        try:
            preset = validate_task(task)
            if not preset.hardware_enabled:
                raise HardwareTaskError(
                    "Jetson-local preset is intentionally motion-locked: "
                    + (preset.disabled_reason or "onsite validation is incomplete")
                )
            command = self.command_for(task_id, preset)
            consume_arm_lease(self.arm_file, preset.name)
        except HardwareTaskError as exc:
            writer.emit(
                TaskState.FAILED,
                "task_failed",
                failed_state=TaskState.PRECHECK.value,
                reason=str(exc),
            )
            return TaskState.FAILED

        self.output_dir.mkdir(parents=True, exist_ok=True)
        console_path = self.output_dir / "pipeline-console.log"
        writer.emit(
            TaskState.PRECHECK,
            "state_finished",
            outcome=Outcome.SUCCESS.value,
            reason="relay spec and one-shot onsite arming lease validated",
        )
        if preset.execution_kind == "fixed_face_cream_rollout":
            writer.emit(
                TaskState.SET_GRASP_CAMERA,
                "state_started",
                source="fixed-workspace local rollout",
            )
            writer.emit(
                TaskState.GRASPING,
                "state_started",
                source="fixed-workspace local rollout",
            )

        master_fd, slave_fd = pty.openpty()
        environment = os.environ.copy()
        environment["FORESTBRIDGE_DEMO_ARMED"] = "1"
        try:
            process = subprocess.Popen(
                command,
                cwd=self.repo_root,
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            writer.emit(
                TaskState.FAILED,
                "task_failed",
                failed_state=TaskState.PRECHECK.value,
                reason=f"could not start integrated pipeline: {exc}",
            )
            return TaskState.FAILED
        os.close(slave_fd)
        os.write(master_fd, b"AUTO_PIPELINE\n")
        started_s = time.monotonic()
        buffer = b""
        current_state: TaskState | None = None
        stopped = False
        timed_out = False

        try:
            with console_path.open("ab") as console:
                while process.poll() is None:
                    if stop_requested():
                        stopped = True
                        writer.emit(
                            TaskState.STOPPED,
                            "stop_requested_observed",
                            reason="relay stop request observed during integrated pipeline",
                        )
                        if not self._interrupt(process):
                            writer.emit(
                                TaskState.NEEDS_ASSISTANCE,
                                "task_needs_assistance",
                                failed_state=(current_state or TaskState.PRECHECK).value,
                                reason=(
                                    "task process did not exit after SIGINT/SIGTERM; "
                                    "use the onsite 12 V cutoff"
                                ),
                            )
                            raise HardwareTaskError("hardware task did not stop cleanly")
                        break
                    if time.monotonic() - started_s > self.timeout_s:
                        timed_out = True
                        writer.emit(
                            TaskState.FAILED,
                            "task_timeout",
                            failed_state=(current_state or TaskState.PRECHECK).value,
                            reason=f"integrated pipeline exceeded {self.timeout_s:.1f} s",
                        )
                        if not self._interrupt(process):
                            writer.emit(
                                TaskState.NEEDS_ASSISTANCE,
                                "task_needs_assistance",
                                reason="timed-out task process did not stop; use onsite 12 V cutoff",
                            )
                            raise HardwareTaskError("timed-out hardware task did not stop cleanly")
                        break

                    readable, _, _ = select.select([master_fd], [], [], self.poll_s)
                    if not readable:
                        continue
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    console.write(chunk)
                    console.flush()
                    os.write(1, chunk)
                    buffer += chunk
                    while b"\n" in buffer:
                        raw_line, buffer = buffer.split(b"\n", 1)
                        line = raw_line.decode("utf-8", errors="replace")
                        for marker, state in STAGE_MARKERS:
                            if marker in line and state != current_state:
                                current_state = state
                                writer.emit(state, "state_started", source="pipeline-console")
                                break
        except BaseException:
            # A Relay/network failure can surface through writer.emit().  Once
            # the child exists, every exceptional exit must stop its whole
            # process group before the worker itself is allowed to unwind.
            self._interrupt(process)
            raise
        finally:
            os.close(master_fd)

        return_code = process.wait()
        if stopped:
            writer.emit(
                TaskState.STOPPED,
                "task_stopped",
                reason=f"integrated pipeline exited after stop request (rc={return_code})",
            )
            return TaskState.STOPPED
        if timed_out:
            return TaskState.FAILED
        if return_code != 0:
            writer.emit(
                TaskState.FAILED,
                "task_failed",
                failed_state=(current_state or TaskState.PRECHECK).value,
                reason=f"integrated pipeline exited with status {return_code}",
            )
            return TaskState.FAILED

        writer.emit(TaskState.VERIFYING_RESULT, "state_started")
        writer.emit(
            TaskState.NEEDS_ASSISTANCE,
            "task_needs_assistance",
            failed_state=TaskState.VERIFYING_RESULT.value,
            reason=(
                "local policy program completed, but autonomous object-grasp/delivery "
                "verification is not implemented"
            ),
            program_completed=True,
        )
        return TaskState.NEEDS_ASSISTANCE
