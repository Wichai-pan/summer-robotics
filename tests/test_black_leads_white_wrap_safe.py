from black_leads_white_wrap_safe import (
    POSITION_JOINTS,
    cyclic_angle_error_deg,
    folded_pose_violations,
    relative_position_targets,
    slew_positions,
)


def pose(value: float) -> dict[str, float]:
    return {
        "shoulder_pan": value,
        "shoulder_lift": value,
        "elbow_flex": value,
        "wrist_flex": value,
        "wrist_roll": value,
        "gripper": value,
    }


def test_relative_targets_exclude_wrist_position() -> None:
    target = relative_position_targets(
        pose(15.0),
        pose(10.0),
        pose(-20.0),
        {joint: 1.0 for joint in pose(0.0)},
        {joint: (-180.0, 180.0) for joint in POSITION_JOINTS},
        True,
        30.0,
        30.0,
    )
    assert "wrist_roll" not in target
    assert target["elbow_flex"] == -15.0


def test_relative_targets_clamp_to_calibration() -> None:
    target = relative_position_targets(
        pose(100.0),
        pose(0.0),
        pose(0.0),
        {joint: 1.0 for joint in pose(0.0)},
        {joint: (-20.0, 20.0) for joint in POSITION_JOINTS},
        True,
        30.0,
        30.0,
    )
    assert all(value == 20.0 for value in target.values())


def test_position_slew_uses_separate_gripper_rate() -> None:
    command = {joint: 0.0 for joint in POSITION_JOINTS}
    target = {joint: 10.0 for joint in POSITION_JOINTS}
    result = slew_positions(command, target, arm_step=1.5, gripper_step=3.0)
    assert result["shoulder_pan"] == 1.5
    assert result["gripper"] == 3.0


def test_folded_pose_wrist_uses_shortest_cyclic_difference() -> None:
    assert cyclic_angle_error_deg(-179.0, 179.0) == 2.0
    assert cyclic_angle_error_deg(179.0, -179.0) == -2.0
    current = pose(0.0)
    reference = pose(0.0)
    current["wrist_roll"] = -179.0
    reference["wrist_roll"] = 179.0
    assert folded_pose_violations(current, reference, 3.0, 3.0) == {}


def test_folded_pose_reports_only_values_outside_tolerance() -> None:
    current = pose(0.0)
    reference = pose(0.0)
    current["elbow_flex"] = 8.1
    current["gripper"] = 9.0
    violations = folded_pose_violations(current, reference, 8.0, 10.0)
    assert violations == {"elbow_flex": 8.1}
