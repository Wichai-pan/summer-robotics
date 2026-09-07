from black_leads_white_wrap_safe import (
    POSITION_JOINTS,
    build_recording_end_snapshot,
    cyclic_angle_error_deg,
    folded_pose_violations,
    relative_position_targets,
    session_position_bounds,
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


def test_rebased_follow_starts_without_a_target_jump_and_keeps_original_limits() -> None:
    calibration = {joint: (-180.0, 180.0) for joint in POSITION_JOINTS}
    original_start = {joint: 10.0 for joint in POSITION_JOINTS}
    bounds = session_position_bounds(
        calibration,
        original_start,
        full_range=False,
        arm_limit=30.0,
        gripper_limit=20.0,
    )
    leader_rebase = pose(75.0)
    follower_rebase = pose(25.0)
    target = relative_position_targets(
        leader_rebase,
        leader_rebase,
        follower_rebase,
        {joint: 1.0 for joint in pose(0.0)},
        bounds,
        True,
        30.0,
        20.0,
    )

    assert target == {joint: 25.0 for joint in POSITION_JOINTS}
    assert bounds["shoulder_pan"] == (-20.0, 40.0)
    assert bounds["gripper"] == (-10.0, 30.0)


def test_recording_end_snapshot_contains_the_actual_full_sent_action() -> None:
    feedback = pose(1.0)
    command = {joint: 2.0 for joint in POSITION_JOINTS}
    snapshot = build_recording_end_snapshot(
        white_state=feedback,
        position_command=command,
        wrist_velocity_raw=-4,
        wrist_target_deg=3.0,
        wrist_actual_deg=2.5,
    )

    assert snapshot["white_state"] == feedback
    assert snapshot["action"] == {
        **command,
        "wrist_roll": -4 * 360.0 / 4096,
    }
    assert snapshot["action_semantics"]["wrist_roll"] == "velocity_deg_s"


def test_folded_pose_wrist_uses_shortest_cyclic_difference() -> None:
    assert cyclic_angle_error_deg(-179.0, 179.0) == 2.0
    assert cyclic_angle_error_deg(179.0, -179.0) == -2.0
    current = pose(0.0)
    reference = pose(0.0)
    current["wrist_roll"] = -179.0
    reference["wrist_roll"] = 179.0
    assert folded_pose_violations(current, reference, 3.0, 3.0) == {}


def test_folded_pose_wrist_uses_raw_ticks_across_encoder_wrap() -> None:
    current = pose(0.0)
    reference = pose(0.0)
    # Saved at raw 4054 and re-read just across the 4095/0 boundary. This is
    # only 47 ticks (~4.1 deg), not a long-path turn or a normalized-angle jump.
    assert folded_pose_violations(
        current,
        reference,
        5.0,
        5.0,
        current_wrist_raw=5,
        reference_wrist_raw=4054,
    ) == {}


def test_folded_pose_reports_only_values_outside_tolerance() -> None:
    current = pose(0.0)
    reference = pose(0.0)
    current["elbow_flex"] = 8.1
    current["gripper"] = 9.0
    violations = folded_pose_violations(current, reference, 8.0, 10.0)
    assert violations == {"elbow_flex": 8.1}
