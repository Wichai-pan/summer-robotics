from act_white_hold_smoke import hold_violations


def test_hold_violations_uses_joint_specific_limits() -> None:
    start = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 0.0,
    }
    current = dict(start)
    current["shoulder_pan"] = 2.1
    current["gripper"] = 4.9
    assert hold_violations(start, current, 1.9, 2.0, 5.0, 2.0) == {
        "shoulder_pan": 2.1
    }
    assert hold_violations(start, current, 2.1, 3.0, 4.0, 2.0) == {
        "gripper": 4.9,
        "wrist_roll": 2.1,
    }
