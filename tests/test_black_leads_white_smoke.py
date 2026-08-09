from black_leads_white_smoke import (
    absolute_targets,
    bounded_relative_targets,
    clamp_to_bounds,
    slew_toward,
    target_bound_violations,
    wrapped_delta_deg,
)


JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


def pose(value: float) -> dict[str, float]:
    return {joint: value for joint in JOINTS}


def test_relative_mapping_uses_separate_starting_poses() -> None:
    targets = bounded_relative_targets(
        black_now=pose(13.0),
        black_start=pose(10.0),
        white_start=pose(-20.0),
        signs={joint: 1.0 for joint in JOINTS},
        max_delta_deg=5.0,
        max_gripper_delta=10.0,
    )
    assert targets["shoulder_pan.pos"] == -17.0


def test_mapping_clamps_and_can_invert_one_joint() -> None:
    signs = {joint: 1.0 for joint in JOINTS}
    signs["shoulder_pan"] = -1.0
    targets = bounded_relative_targets(
        black_now=pose(30.0),
        black_start=pose(10.0),
        white_start=pose(50.0),
        signs=signs,
        max_delta_deg=5.0,
        max_gripper_delta=10.0,
    )
    assert targets["shoulder_pan.pos"] == 45.0
    assert targets["shoulder_lift.pos"] == 55.0
    assert targets["gripper.pos"] == 60.0


def test_full_range_removes_only_startup_excursion_limit() -> None:
    targets = bounded_relative_targets(
        black_now=pose(40.0),
        black_start=pose(10.0),
        white_start=pose(0.0),
        signs={joint: 1.0 for joint in JOINTS},
        max_delta_deg=5.0,
        max_gripper_delta=10.0,
        full_range=True,
    )
    assert targets["shoulder_pan.pos"] == 30.0


def test_calibrated_bounds_and_slew_still_apply_in_full_range() -> None:
    desired = {f"{joint}.pos": 40.0 for joint in JOINTS}
    bounded = clamp_to_bounds(
        desired,
        {joint: (-20.0, 20.0) for joint in JOINTS},
    )
    command = slew_toward(
        {f"{joint}.pos": 0.0 for joint in JOINTS},
        bounded,
        arm_step=1.5,
        gripper_step=3.0,
    )
    assert command["shoulder_pan.pos"] == 1.5
    assert command["gripper.pos"] == 3.0


def test_absolute_mapping_copies_calibrated_pose_and_inverts_selected_joint() -> None:
    leader = pose(12.0)
    leader["wrist_roll"] = -35.0
    leader["gripper"] = 150.0
    signs = {joint: 1.0 for joint in JOINTS}
    signs["wrist_roll"] = -1.0

    targets = absolute_targets(leader, signs)

    assert targets["shoulder_pan.pos"] == 12.0
    assert targets["wrist_roll.pos"] == 35.0
    assert targets["gripper.pos"] == 100.0


def test_absolute_target_bound_violations_report_only_outside_joints() -> None:
    action = {f"{joint}.pos": 0.0 for joint in JOINTS}
    action["elbow_flex.pos"] = 25.0
    bounds = {joint: (-20.0, 20.0) for joint in JOINTS}

    violations = target_bound_violations(action, bounds)

    assert violations == {"elbow_flex": (25.0, -20.0, 20.0)}


def test_wrist_delta_is_continuous_across_encoder_wrap() -> None:
    assert wrapped_delta_deg(-179.0, 179.0) == 2.0
    assert wrapped_delta_deg(179.0, -179.0) == -2.0
