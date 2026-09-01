from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "forestbridge_task_executive.py"
SPEC = importlib.util.spec_from_file_location("forestbridge_task_executive", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def make_executive(tmp_path: Path, runner, stop_file: Path | None = None):
    writer = MODULE.EventWriter(
        task_id="test-task",
        events_path=tmp_path / "events.jsonl",
        status_path=tmp_path / "status.json",
    )
    return MODULE.TaskExecutive(runner=runner, writer=writer, stop_file=stop_file)


def test_dry_run_completes_and_publishes_atomic_status(tmp_path: Path) -> None:
    executive = make_executive(tmp_path, MODULE.DryRunSkillRunner())

    final_state = executive.run(MODULE.TaskSpec(task_id="test-task"))

    assert final_state == MODULE.TaskState.COMPLETE
    events = read_events(tmp_path / "events.jsonl")
    assert events[-1]["state"] == "complete"
    assert events[-1]["event"] == "task_completed"
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8")) == events[-1]
    assert not (tmp_path / ".status.json.tmp").exists()


def test_retryable_failure_retries_once_then_completes(tmp_path: Path) -> None:
    runner = MODULE.DryRunSkillRunner(fail_once=MODULE.TaskState.LOCALIZING)
    executive = make_executive(tmp_path, runner)

    final_state = executive.run(MODULE.TaskSpec(task_id="test-task"))

    assert final_state == MODULE.TaskState.COMPLETE
    events = read_events(tmp_path / "events.jsonl")
    retries = [event for event in events if event["event"] == "state_retrying"]
    assert len(retries) == 1
    starts = [
        event
        for event in events
        if event["state"] == "localizing" and event["event"] == "state_started"
    ]
    assert [event["attempt"] for event in starts] == [1, 2]


def test_uncertain_result_never_advances_to_next_motion_state(tmp_path: Path) -> None:
    runner = MODULE.DryRunSkillRunner(uncertain=MODULE.TaskState.VERIFYING_DOCK)
    executive = make_executive(tmp_path, runner)

    final_state = executive.run(MODULE.TaskSpec(task_id="test-task"))

    assert final_state == MODULE.TaskState.NEEDS_ASSISTANCE
    events = read_events(tmp_path / "events.jsonl")
    assert events[-1]["state"] == "needs_assistance"
    assert not any(event["state"] == "set_grasp_camera" for event in events)


def test_existing_stop_file_stops_before_first_skill(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    stop_file.touch()
    executive = make_executive(tmp_path, MODULE.DryRunSkillRunner(), stop_file=stop_file)

    final_state = executive.run(MODULE.TaskSpec(task_id="test-task"))

    assert final_state == MODULE.TaskState.STOPPED
    events = read_events(tmp_path / "events.jsonl")
    assert [event["event"] for event in events] == ["task_started", "task_stopped"]
