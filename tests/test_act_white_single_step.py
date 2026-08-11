import json
import time

import pytest

from act_white_single_step import (
    bounded_position_targets,
    load_plan,
    plan_state_violations,
)


def test_bounded_position_targets_relimits_plan_against_fresh_state() -> None:
    current = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 1.0,
        "elbow_flex": 2.0,
        "wrist_flex": 3.0,
        "gripper": 4.0,
    }
    requested = {
        "shoulder_pan.pos": 20.0,
        "shoulder_lift.pos": -20.0,
        "elbow_flex.pos": 2.5,
        "wrist_flex.pos": 3.0,
        "gripper.pos": 20.0,
    }
    assert bounded_position_targets(current, requested, 1.0, 2.0) == {
        "shoulder_pan": 1.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 2.5,
        "wrist_flex": 3.0,
        "gripper": 6.0,
    }


def test_plan_state_violations_uses_separate_limits() -> None:
    planned = {f"{name}.pos": 0.0 for name in (*(
        "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex"
    ), "gripper")}
    current = {name.removesuffix(".pos"): value for name, value in planned.items()}
    current["shoulder_pan"] = 2.1
    current["gripper"] = 3.9
    assert plan_state_violations(planned, current, 1.9, 2.0, 4.0, 2.0) == {
        "shoulder_pan": 2.1
    }


def test_load_plan_rejects_stale_file(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "schema": "forestbridge_act_guarded_step/v1",
                "created_unix_s": time.time() - 10.0,
            }
        )
    )
    with pytest.raises(RuntimeError, match="stale"):
        load_plan(path, max_age_s=1.0)
