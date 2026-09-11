from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path


TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "forestbridge_hardware_task_executor.py"
SPEC = importlib.util.spec_from_file_location("forestbridge_hardware_task_executor", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

from forestbridge_task_executive import EventWriter, TaskState  # noqa: E402


def relay_task(**overrides):
    spec = {
        "preset": "table_pick_place_01",
        "task_type": "navigate_then_pick_place",
        "goal_x_m": 0.052,
        "goal_y_m": -0.357,
        "goal_yaw_deg": -90.0,
        "act_steps": 600,
    }
    spec.update(overrides)
    return {"task_id": "a" * 32, "spec": spec}


def local_rollout_task(**overrides):
    spec = {
        "preset": "local_face_cream_rollout_01",
        "task_type": "local_pick_place",
        "goal_x_m": 0.0,
        "goal_y_m": 0.0,
        "goal_yaw_deg": 0.0,
        "act_steps": 20,
    }
    spec.update(overrides)
    return {"task_id": "b" * 32, "spec": spec}


def write_arm_file(
    path: Path,
    expires_epoch_s: float = 200.0,
    preset: str = "table_pick_place_01",
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": MODULE.ARM_SCHEMA,
                "token": MODULE.ARM_TOKEN,
                "preset": preset,
                "expires_epoch_s": expires_epoch_s,
            }
        ),
        encoding="utf-8",
    )


def make_writer(tmp_path: Path) -> EventWriter:
    return EventWriter(
        task_id="a" * 32,
        events_path=tmp_path / "events.jsonl",
        status_path=tmp_path / "status.json",
    )


def enable_test_preset():
    original = MODULE.LOCAL_PRESETS["table_pick_place_01"]
    MODULE.LOCAL_PRESETS["table_pick_place_01"] = replace(
        original, hardware_enabled=True, disabled_reason=""
    )
    return original


def full_cycle_task(**overrides):
    spec = {
        "preset": "small_cup_full_cycle_01",
        "task_type": "carry_delivery",
        "goal_x_m": 0.0,
        "goal_y_m": 0.0,
        "goal_yaw_deg": 0.0,
        "act_steps": 500,
    }
    spec.update(overrides)
    return {"task_id": "c" * 32, "spec": spec}


def test_local_allowlist_rejects_modified_coordinates() -> None:
    preset = MODULE.validate_task(relay_task())
    assert preset.name == "table_pick_place_01"

    try:
        MODULE.validate_task(relay_task(goal_x_m=99))
    except MODULE.HardwareTaskError as exc:
        assert "goal_x_m" in str(exc)
    else:
        raise AssertionError("modified relay coordinates were accepted")


def test_fixed_workspace_rollout_is_allowlisted_without_base_motion(tmp_path: Path) -> None:
    preset = MODULE.validate_task(local_rollout_task())
    assert preset.execution_kind == "fixed_face_cream_rollout"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "jetson_smolvla_white_rollout.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    executor = MODULE.HardwarePipelineExecutor(
        repo_root=tmp_path,
        arm_file=tmp_path / "arm.json",
        output_dir=tmp_path / "output",
    )
    command = executor.command_for("b" * 32, preset)
    assert command[-3:] == ["--execute", "--steps", "20"]
    assert "nav" not in " ".join(command)


def test_small_cup_full_cycle_is_fixed_deploy_script_and_requires_matching_lease(tmp_path: Path) -> None:
    preset = MODULE.validate_task(full_cycle_task())
    assert preset.execution_kind == "small_cup_full_cycle"
    assert preset.requires_arm_lease is True
    assert preset.execution_timeout_s == 900.0


def test_unrevalidated_production_preset_is_motion_locked(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    scripts = repo_root / "scripts"
    scripts.mkdir(parents=True)
    marker = tmp_path / "started"
    (scripts / "jetson_nav_then_act_pick_place.sh").write_text(
        f"#!/usr/bin/env bash\ntouch {marker}\n",
        encoding="utf-8",
    )
    arm_file = tmp_path / "arm.json"
    write_arm_file(arm_file, expires_epoch_s=10_000_000_000.0)
    executor = MODULE.HardwarePipelineExecutor(
        repo_root=repo_root,
        arm_file=arm_file,
        output_dir=tmp_path / "output",
    )

    final_state = executor.run(relay_task(), make_writer(tmp_path), lambda: False)

    assert final_state == TaskState.FAILED
    assert arm_file.exists()
    assert not marker.exists()
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert "motion-locked" in status["reason"]


def test_arm_lease_is_expiring_and_one_shot(tmp_path: Path) -> None:
    arm_file = tmp_path / "arm.json"
    write_arm_file(arm_file)
    MODULE.consume_arm_lease(arm_file, "table_pick_place_01", now_s=100.0)
    assert not arm_file.exists()

    write_arm_file(arm_file, expires_epoch_s=50.0)
    try:
        MODULE.consume_arm_lease(arm_file, "table_pick_place_01", now_s=100.0)
    except MODULE.HardwareTaskError as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("expired arm lease was accepted")


def test_hardware_pipeline_runs_fixed_argv_but_does_not_claim_delivery_verified(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    scripts = repo_root / "scripts"
    scripts.mkdir(parents=True)
    pipeline = scripts / "jetson_nav_then_act_pick_place.sh"
    pipeline.write_text(
        "#!/usr/bin/env bash\n"
        "read -r token\n"
        "[[ \"$token\" == AUTO_PIPELINE ]]\n"
        "echo '=== 1/5 RETURN WHITE ARM TO FOLDED TRAVEL POSE ==='\n"
        "echo '=== 2/5 RETURN GEMINI TO MAPPING REFERENCE ==='\n"
        "echo '=== 3/5 NAVIGATE TO TABLE DOCKING POSE ==='\n"
        "echo 'Nav2 path is ready'\n"
        "echo 'AUTO_PIPELINE armed; MOVE is automatically confirmed'\n"
        "echo '=== 4/5 RETURN GEMINI TO ACT GRASP REFERENCE ==='\n"
        "echo '=== 5/5 RUN SUPERVISED ACT PICK/PLACE ==='\n",
        encoding="utf-8",
    )
    arm_file = tmp_path / "arm.json"
    write_arm_file(arm_file, expires_epoch_s=10_000_000_000.0)
    output_dir = tmp_path / "output"
    executor = MODULE.HardwarePipelineExecutor(
        repo_root=repo_root,
        arm_file=arm_file,
        output_dir=output_dir,
        poll_s=0.01,
        timeout_s=2.0,
    )

    original = enable_test_preset()
    try:
        final_state = executor.run(relay_task(), make_writer(tmp_path), lambda: False)
    finally:
        MODULE.LOCAL_PRESETS["table_pick_place_01"] = original

    assert final_state == TaskState.NEEDS_ASSISTANCE
    assert not arm_file.exists()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["mode"] == "hardware-allowlisted"
    assert events[-1]["program_completed"] is True
    assert events[-1]["state"] == "needs_assistance"
    assert b"RUN SUPERVISED ACT" in (output_dir / "pipeline-console.log").read_bytes()


def test_missing_arm_lease_fails_before_process_start(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    scripts = repo_root / "scripts"
    scripts.mkdir(parents=True)
    marker = tmp_path / "started"
    (scripts / "jetson_nav_then_act_pick_place.sh").write_text(
        f"#!/usr/bin/env bash\ntouch {marker}\n",
        encoding="utf-8",
    )
    executor = MODULE.HardwarePipelineExecutor(
        repo_root=repo_root,
        arm_file=tmp_path / "missing-arm.json",
        output_dir=tmp_path / "output",
    )

    original = enable_test_preset()
    try:
        final_state = executor.run(relay_task(), make_writer(tmp_path), lambda: False)
    finally:
        MODULE.LOCAL_PRESETS["table_pick_place_01"] = original

    assert final_state == TaskState.FAILED
    assert not marker.exists()


def test_relay_stop_interrupts_running_pipeline(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    scripts = repo_root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "jetson_nav_then_act_pick_place.sh").write_text(
        "#!/usr/bin/env bash\n"
        "read -r token\n"
        "echo '=== 3/5 NAVIGATE TO TABLE DOCKING POSE ==='\n"
        "sleep 30\n",
        encoding="utf-8",
    )
    arm_file = tmp_path / "arm.json"
    write_arm_file(arm_file, expires_epoch_s=10_000_000_000.0)
    executor = MODULE.HardwarePipelineExecutor(
        repo_root=repo_root,
        arm_file=arm_file,
        output_dir=tmp_path / "output",
        poll_s=0.01,
        interrupt_grace_s=1.0,
        timeout_s=3.0,
    )
    checks = 0

    def stop_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    original = enable_test_preset()
    try:
        final_state = executor.run(relay_task(), make_writer(tmp_path), stop_requested)
    finally:
        MODULE.LOCAL_PRESETS["table_pick_place_01"] = original

    assert final_state == TaskState.STOPPED
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "task_stopped"


def test_event_delivery_failure_stops_running_pipeline(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    scripts = repo_root / "scripts"
    scripts.mkdir(parents=True)
    child_pid = tmp_path / "child.pid"
    (scripts / "jetson_nav_then_act_pick_place.sh").write_text(
        "#!/usr/bin/env bash\n"
        "read -r token\n"
        f"echo $$ > {child_pid}\n"
        "echo '=== 3/5 NAVIGATE TO TABLE DOCKING POSE ==='\n"
        "sleep 30\n",
        encoding="utf-8",
    )
    arm_file = tmp_path / "arm.json"
    write_arm_file(arm_file, expires_epoch_s=10_000_000_000.0)

    def observer(event: dict[str, object]) -> None:
        if event["event"] == "state_started" and event["state"] == "localizing":
            raise ConnectionError("simulated Relay loss")

    writer = EventWriter(
        task_id="a" * 32,
        events_path=tmp_path / "events.jsonl",
        status_path=tmp_path / "status.json",
        observer=observer,
    )
    executor = MODULE.HardwarePipelineExecutor(
        repo_root=repo_root,
        arm_file=arm_file,
        output_dir=tmp_path / "output",
        poll_s=0.01,
        interrupt_grace_s=1.0,
        timeout_s=3.0,
    )

    original = enable_test_preset()
    try:
        try:
            executor.run(relay_task(), writer, lambda: False)
        except ConnectionError as exc:
            assert "Relay loss" in str(exc)
        else:
            raise AssertionError("simulated Relay failure did not escape")
    finally:
        MODULE.LOCAL_PRESETS["table_pick_place_01"] = original

    pid = int(child_pid.read_text(encoding="utf-8"))
    try:
        MODULE.os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("pipeline process survived Relay event-delivery failure")
