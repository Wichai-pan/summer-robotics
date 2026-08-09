from tools.black_leads_white_smoke import (
    bounded_relative_targets,
    clamp_to_bounds,
    slew_toward,
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
