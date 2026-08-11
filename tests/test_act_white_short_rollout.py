import pytest

from act_white_short_rollout import (
    action_dict,
    clamp_position_to_total_envelope,
    total_travel_violations,
)


def test_action_dict_rejects_non_finite_and_dimension_mismatch() -> None:
    assert action_dict(["a", "b"], [1.0, 2.0]) == {"a": 1.0, "b": 2.0}
    with pytest.raises(ValueError, match="equal length"):
        action_dict(["a"], [1.0, 2.0])
    with pytest.raises(ValueError, match="non-finite"):
        action_dict(["a"], [float("nan")])


def test_total_travel_violations_uses_gripper_limit() -> None:
    start = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 0.0,
    }
    current = dict(start)
    current["shoulder_lift"] = -12.1
    current["gripper"] = 23.9
    assert total_travel_violations(start, current, 12.0, 24.0) == {
        "shoulder_lift": pytest.approx(-12.1)
    }


def test_total_envelope_clamps_command_before_transmission() -> None:
    start = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 5.0,
    }
    command = {
        "shoulder_pan": 12.5,
        "shoulder_lift": -13.0,
        "elbow_flex": 1.0,
        "wrist_flex": 0.0,
        "gripper": -30.0,
    }
    bounded, joints = clamp_position_to_total_envelope(command, start, 12.0, 24.0)
    assert bounded == {
        "shoulder_pan": 12.0,
        "shoulder_lift": -12.0,
        "elbow_flex": 1.0,
        "wrist_flex": 0.0,
        "gripper": -19.0,
    }
    assert joints == ["shoulder_pan", "shoulder_lift", "gripper"]
