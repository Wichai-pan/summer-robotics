import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pick_hold_contract_is_versioned_without_replacing_pick_place() -> None:
    payload = json.loads(
        (ROOT / "configs" / "act" / "fixed_scene_facecream_pick_hold_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["task_contract"] == "fixed_pick_hold/v1"
    assert payload["legacy_task_contract_preserved"] == "fixed_pick_place/v1"
    assert payload["joint_order"] == [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ]
    assert payload["action_semantics"]["wrist_roll"].endswith("degrees per second")
    assert payload["dataset_status"] == "quarantine_until_hardware_qa"


def test_dry_run_executes_real_lifecycle_without_hardware_imports() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "grasp_hold_session_dry_run.py")],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    assert payload == {
        "status": "PASS",
        "final_state": "closed",
        "frames_before_boundary": 1,
        "recording_boundaries": 1,
        "control_cycles": 2,
        "forbidden_imports": [],
        "hardware_access": False,
    }
