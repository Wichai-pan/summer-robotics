#!/usr/bin/env python3
"""Deterministic, web-facing ForestBridge task state machine.

This first implementation is deliberately dry-run only.  It establishes the
status/event contract that a web UI and a future Jetson hardware adapter will
share, without opening cameras, serial ports, ROS, or motor controllers.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol


class Outcome(str, Enum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    FATAL_FAILURE = "fatal_failure"
    UNCERTAIN = "uncertain"


class TaskState(str, Enum):
    PRECHECK = "precheck"
    SET_MAPPING_CAMERA = "set_mapping_camera"
    LOCALIZING = "localizing"
    PLANNING = "planning"
    NAVIGATING = "navigating"
    VERIFYING_DOCK = "verifying_dock"
    SET_GRASP_CAMERA = "set_grasp_camera"
    GRASPING = "grasping"
    VERIFYING_RESULT = "verifying_result"
    COMPLETE = "complete"
    FAILED = "failed"
    NEEDS_ASSISTANCE = "needs_assistance"
    STOPPED = "stopped"


WORKFLOW = (
    TaskState.PRECHECK,
    TaskState.SET_MAPPING_CAMERA,
    TaskState.LOCALIZING,
    TaskState.PLANNING,
    TaskState.NAVIGATING,
    TaskState.VERIFYING_DOCK,
    TaskState.SET_GRASP_CAMERA,
    TaskState.GRASPING,
    TaskState.VERIFYING_RESULT,
)

# Retries are intentionally finite.  A future hardware adapter may add a
# recovery action, but it must not turn an unknown failure into an endless loop.
MAX_ATTEMPTS = {
    TaskState.LOCALIZING: 2,
    TaskState.PLANNING: 2,
    TaskState.VERIFYING_DOCK: 2,
    TaskState.GRASPING: 2,
    TaskState.VERIFYING_RESULT: 2,
}


@dataclass(frozen=True)
class SkillResult:
    outcome: Outcome
    reason: str


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    task_type: str = "navigate_then_pick_place"
    map_database: str = "/data/slam/mapping/20260825T131710Z/rtabmap.db"
    goal_x_m: float = 0.052
    goal_y_m: float = -0.357
    goal_yaw_deg: float = -90.0
    act_steps: int = 600


class SkillRunner(Protocol):
    def run(self, state: TaskState, attempt: int, spec: TaskSpec) -> SkillResult:
        """Run one state without deciding what state comes next."""


class DryRunSkillRunner:
    """Offline runner used to validate orchestration and UI integration."""

    def __init__(
        self,
        fail_once: TaskState | None = None,
        uncertain: TaskState | None = None,
        delay_s: float = 0.0,
    ):
        self.fail_once = fail_once
        self.uncertain = uncertain
        self.delay_s = delay_s

    def run(self, state: TaskState, attempt: int, spec: TaskSpec) -> SkillResult:
        del spec
        if self.delay_s:
            time.sleep(self.delay_s)
        if state == self.uncertain:
            return SkillResult(Outcome.UNCERTAIN, f"dry-run uncertainty injected at {state.value}")
        if state == self.fail_once and attempt == 1:
            return SkillResult(
                Outcome.RETRYABLE_FAILURE,
                f"dry-run retryable failure injected at {state.value}",
            )
        return SkillResult(Outcome.SUCCESS, f"dry-run {state.value} passed")


class EventWriter:
    def __init__(
        self,
        task_id: str,
        events_path: Path,
        status_path: Path,
        observer: Callable[[dict[str, object]], None] | None = None,
    ):
        self.task_id = task_id
        self.events_path = events_path
        self.status_path = status_path
        self.observer = observer
        self.sequence = 0
        events_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, state: TaskState, event: str, **fields: object) -> dict[str, object]:
        self.sequence += 1
        payload: dict[str, object] = {
            "schema": "forestbridge/task-event/v1",
            "sequence": self.sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "state": state.value,
            "event": event,
            **fields,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        self._atomic_write_status(payload)
        if self.observer is not None:
            self.observer(payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
        return payload

    def _atomic_write_status(self, payload: dict[str, object]) -> None:
        temporary = self.status_path.with_name(f".{self.status_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.status_path)


class TaskExecutive:
    def __init__(
        self,
        runner: SkillRunner,
        writer: EventWriter,
        stop_file: Path | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ):
        self.runner = runner
        self.writer = writer
        self.stop_file = stop_file
        self.stop_requested = stop_requested

    def run(self, spec: TaskSpec) -> TaskState:
        self.writer.emit(TaskState.PRECHECK, "task_started", spec=asdict(spec), mode="dry-run")
        for state in WORKFLOW:
            local_stop = self.stop_file is not None and self.stop_file.exists()
            remote_stop = self.stop_requested is not None and self.stop_requested()
            if local_stop or remote_stop:
                self.writer.emit(
                    TaskState.STOPPED,
                    "task_stopped",
                    reason="stop request observed before next skill",
                )
                return TaskState.STOPPED

            max_attempts = MAX_ATTEMPTS.get(state, 1)
            for attempt in range(1, max_attempts + 1):
                self.writer.emit(state, "state_started", attempt=attempt, max_attempts=max_attempts)
                result = self.runner.run(state, attempt, spec)
                self.writer.emit(
                    state,
                    "state_finished",
                    attempt=attempt,
                    outcome=result.outcome.value,
                    reason=result.reason,
                )
                if result.outcome == Outcome.SUCCESS:
                    break
                if result.outcome == Outcome.RETRYABLE_FAILURE and attempt < max_attempts:
                    self.writer.emit(state, "state_retrying", next_attempt=attempt + 1)
                    continue
                if result.outcome == Outcome.UNCERTAIN:
                    self.writer.emit(
                        TaskState.NEEDS_ASSISTANCE,
                        "task_needs_assistance",
                        failed_state=state.value,
                        reason=result.reason,
                    )
                    return TaskState.NEEDS_ASSISTANCE
                self.writer.emit(
                    TaskState.FAILED,
                    "task_failed",
                    failed_state=state.value,
                    reason=result.reason,
                )
                return TaskState.FAILED

        self.writer.emit(TaskState.COMPLETE, "task_completed")
        return TaskState.COMPLETE


def parse_state(value: str) -> TaskState:
    try:
        state = TaskState(value)
    except ValueError as exc:
        choices = ", ".join(state.value for state in WORKFLOW)
        raise argparse.ArgumentTypeError(f"state must be one of: {choices}") from exc
    if state not in WORKFLOW:
        raise argparse.ArgumentTypeError("only workflow states may be injected")
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--fail-once", type=parse_state)
    parser.add_argument("--uncertain", type=parse_state)
    parser.add_argument("--delay-s", type=float, default=0.0)
    parser.add_argument("--goal-x", type=float, default=0.052)
    parser.add_argument("--goal-y", type=float, default=-0.357)
    parser.add_argument("--goal-yaw-deg", type=float, default=-90.0)
    parser.add_argument("--act-steps", type=int, default=600)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.act_steps <= 0:
        raise SystemExit("--act-steps must be positive")
    if args.delay_s < 0:
        raise SystemExit("--delay-s cannot be negative")
    spec = TaskSpec(
        task_id=args.task_id,
        goal_x_m=args.goal_x,
        goal_y_m=args.goal_y,
        goal_yaw_deg=args.goal_yaw_deg,
        act_steps=args.act_steps,
    )
    writer = EventWriter(
        task_id=spec.task_id,
        events_path=args.output_dir / "events.jsonl",
        status_path=args.output_dir / "status.json",
    )
    executive = TaskExecutive(
        runner=DryRunSkillRunner(
            fail_once=args.fail_once,
            uncertain=args.uncertain,
            delay_s=args.delay_s,
        ),
        writer=writer,
        stop_file=args.stop_file,
    )
    final_state = executive.run(spec)
    return 0 if final_state == TaskState.COMPLETE else 1


if __name__ == "__main__":
    raise SystemExit(main())
