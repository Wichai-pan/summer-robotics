from return_white_to_folded_pose import (
    return_errors,
    slew_return_positions,
    within_final_tolerance,
)


def test_slew_return_positions_uses_arm_and_gripper_rates() -> None:
    command = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 0.0,
    }
    target = {joint: 10.0 for joint in command}
    assert slew_return_positions(command, target, 0.4, 1.0) == {
        "shoulder_pan": 0.4,
        "shoulder_lift": 0.4,
        "elbow_flex": 0.4,
        "wrist_flex": 0.4,
        "gripper": 1.0,
    }


def test_return_tolerance_is_joint_specific() -> None:
    current = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 0.0,
    }
    target = dict(current)
    errors = return_errors(current, target, wrist_error_deg=1.9)
    assert within_final_tolerance(errors, 2.0, 3.0, 2.0)
    errors["shoulder_pan"] = 2.1
    assert not within_final_tolerance(errors, 2.0, 3.0, 2.0)
