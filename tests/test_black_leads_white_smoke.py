from tools.black_leads_white_smoke import bounded_relative_targets


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
