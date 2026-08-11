import pytest

from act_white_short_rollout import (
    action_dict,
    clamp_position_to_total_envelope,
    rollout_guarded_action,
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


def test_rollout_guard_slews_command_and_bounds_feedback_error() -> None:
    guarded, reasons = rollout_guarded_action(
        predicted=[70.0, 5.0, 80.0],
        action_names=["elbow_flex.pos", "wrist_roll.vel_deg_s", "gripper.pos"],
        action_minimum=[-100.0, -8.0, 0.0],
        action_maximum=[100.0, 8.0, 100.0],
        previous_command={"elbow_flex": 95.0, "gripper": 5.0},
        feedback={"elbow_flex": 95.0, "gripper": 5.0},
        arm_step=1.0,
        gripper_step=2.0,
        wrist_speed_limit=1.0,
        arm_tracking_limit=4.0,
        gripper_tracking_limit=8.0,
    )
    assert guarded == {
        "elbow_flex.pos": 94.0,
        "wrist_roll.vel_deg_s": 1.0,
        "gripper.pos": 7.0,
    }
    assert reasons == {
        "elbow_flex.pos": ["command_slew"],
        "wrist_roll.vel_deg_s": ["wrist_speed"],
        "gripper.pos": ["command_slew"],
    }

    guarded, reasons = rollout_guarded_action(
        predicted=[70.0],
        action_names=["elbow_flex.pos"],
        action_minimum=[-100.0],
        action_maximum=[100.0],
        previous_command={"elbow_flex": 91.0},
        feedback={"elbow_flex": 95.0},
        arm_step=1.0,
        gripper_step=2.0,
        wrist_speed_limit=1.0,
        arm_tracking_limit=4.0,
        gripper_tracking_limit=8.0,
    )
    assert guarded == {"elbow_flex.pos": 91.0}
    assert reasons == {
        "elbow_flex.pos": ["command_slew", "tracking_envelope"]
    }
