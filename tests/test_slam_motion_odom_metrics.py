import math

from tools.slam_motion_odom_metrics import MotionThresholds, analyze_records


def quaternion(yaw_deg: float) -> list[float]:
    half = math.radians(yaw_deg) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def records(points: list[tuple[float, float, float]], yaws: list[float]) -> list[dict]:
    output: list[dict] = []
    for index, (point, yaw) in enumerate(zip(points, yaws, strict=True)):
        stamp = index * 0.1
        output.extend(
            [
                {"type": "odom", "stamp_s": stamp, "receive_monotonic_s": 10 + stamp,
                 "frame_id": "odom", "child_frame_id": "base_link", "position": list(point), "orientation": quaternion(yaw)},
                {"type": "odom_info", "stamp_s": stamp, "receive_monotonic_s": 10 + stamp,
                 "lost": False, "features": 120, "inliers": 90},
            ]
        )
    return output


LIMITS = MotionThresholds(minimum_duration_s=0.2)


def test_fake_static_straight_turn_and_in_place_rotation_pass() -> None:
    static = records([(0, 0, 0), (0, 0, 0), (0, 0, 0)], [0, 0, 0])
    straight = records([(0, 0, 0), (0.03, 0, 0), (0.06, 0, 0)], [0, 0, 0])
    turn = records([(0, 0, 0), (0.03, 0, 0), (0.03, 0, 0)], [0, 0, 12])
    rotation = records([(0, 0, 0), (0, 0, 0), (0, 0, 0)], [0, 12, 24])

    for sample in (static, straight, turn, rotation):
        assert analyze_records(sample, LIMITS)["status"] == "PASS"
    assert analyze_records(straight, LIMITS)["path_length_m"] == 0.06
    assert analyze_records(turn, LIMITS)["segment_stats"]["turn"]["count"] == 1


def test_time_gap_receive_stall_tracking_loss_jump_and_speed_fail() -> None:
    base = records([(0, 0, 0), (0.03, 0, 0), (0.06, 0, 0)], [0, 0, 0])
    cases: list[list[dict]] = []
    gap = [dict(record) for record in base]
    gap[2]["stamp_s"] = 1.0
    cases.append(gap)
    stall = [dict(record) for record in base]
    stall[2]["receive_monotonic_s"] = 11.0
    cases.append(stall)
    lost = [dict(record) for record in base]
    lost[3]["lost"] = True
    cases.append(lost)
    jump = records([(0, 0, 0), (0.5, 0, 0), (0.53, 0, 0)], [0, 0, 0])
    cases.append(jump)
    rotation_jump = records([(0, 0, 0), (0, 0, 0), (0, 0, 0)], [0, 90, 90])
    cases.append(rotation_jump)
    speed = records([(0, 0, 0), (0.15, 0, 0), (0.3, 0, 0)], [0, 0, 0])
    cases.append(speed)

    for sample in cases:
        assert analyze_records(sample, LIMITS)["status"] == "FAIL"


def test_missing_quality_field_is_a_reported_failure() -> None:
    sample = records([(0, 0, 0), (0.03, 0, 0), (0.06, 0, 0)], [0, 0, 0])
    del sample[1]["features"]

    report = analyze_records(sample, LIMITS)

    assert report["status"] == "FAIL"
    assert any("missing features" in failure for failure in report["failures"])
    assert report["median_features"] == 120


def test_non_finite_and_non_normalized_pose_are_reported_failures() -> None:
    non_finite = records([(0, 0, 0), (0.03, 0, 0), (0.06, 0, 0)], [0, 0, 0])
    non_finite[0]["position"] = [float("nan"), 0.0, 0.0]
    non_normalized = records([(0, 0, 0), (0.03, 0, 0), (0.06, 0, 0)], [0, 0, 0])
    non_normalized[0]["orientation"] = [0.0, 0.0, 0.0, 2.0]

    assert analyze_records(non_finite, LIMITS)["status"] == "FAIL"
    report = analyze_records(non_normalized, LIMITS)
    assert report["status"] == "FAIL"
    assert any("normalized" in failure for failure in report["failures"])
