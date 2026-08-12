import math

from tools.slam_static_odom_metrics import Thresholds, analyze_records


def quaternion_from_yaw(degrees: float) -> list[float]:
    half = math.radians(degrees) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def synthetic_records(
    *, duration_s: float = 60.0, rate_hz: float = 10.0, drift_m: float = 0.005
) -> list[dict]:
    count = int(duration_s * rate_hz) + 1
    records: list[dict] = []
    for index in range(count):
        fraction = index / (count - 1)
        stamp = index / rate_hz
        records.append(
            {
                "type": "odom",
                "stamp_s": stamp,
                "receive_monotonic_s": 100.0 + stamp,
                "frame_id": "odom",
                "child_frame_id": "camera_link",
                "position": [drift_m * fraction, 0.0, 0.0],
                "orientation": quaternion_from_yaw(0.2 * fraction),
            }
        )
        records.append(
            {
                "type": "odom_info",
                "stamp_s": stamp,
                "receive_monotonic_s": 100.0 + stamp,
                "lost": False,
                "features": 150,
                "inliers": 90,
            }
        )
    return records


def test_stable_static_odometry_passes() -> None:
    report = analyze_records(synthetic_records())
    assert report["status"] == "PASS"
    assert report["lost_events"] == 0
    assert report["translation_drift_m"] == 0.005
    assert report["rotation_drift_deg"] == 0.2


def test_large_excursion_and_tracking_loss_fail() -> None:
    records = synthetic_records(drift_m=0.04)
    records[21]["lost"] = True
    report = analyze_records(records)
    assert report["status"] == "FAIL"
    assert report["lost_events"] == 1
    assert any("translation excursion" in failure for failure in report["failures"])
    assert any("lost events" in failure for failure in report["failures"])


def test_timestamp_gap_fails_even_when_final_pose_is_stable() -> None:
    records = synthetic_records(duration_s=6.0, rate_hz=10.0)
    odom = [record for record in records if record["type"] == "odom"]
    for record in odom[30:]:
        record["stamp_s"] += 1.0
    report = analyze_records(records, Thresholds(minimum_duration_s=5.0))
    assert report["status"] == "FAIL"
    assert report["maximum_gap_s"] == 1.1
    assert any("maximum gap" in failure for failure in report["failures"])


def test_receive_stall_fails_when_message_stamps_look_continuous() -> None:
    records = synthetic_records(duration_s=6.0, rate_hz=10.0)
    odom = [record for record in records if record["type"] == "odom"]
    for record in odom[30:]:
        record["receive_monotonic_s"] += 2.0
    report = analyze_records(records, Thresholds(minimum_duration_s=5.0))
    assert report["status"] == "FAIL"
    assert report["maximum_gap_s"] == 0.1
    assert report["maximum_receive_gap_s"] == 2.1
    assert any("maximum receive gap" in failure for failure in report["failures"])


def test_quality_receive_stall_fails_when_message_stamps_look_continuous() -> None:
    records = synthetic_records(duration_s=6.0, rate_hz=10.0)
    info = [record for record in records if record["type"] == "odom_info"]
    for record in info[30:]:
        record["receive_monotonic_s"] += 2.0
    report = analyze_records(records, Thresholds(minimum_duration_s=5.0))
    assert report["status"] == "FAIL"
    assert report["maximum_odom_info_receive_gap_s"] == 2.1
    assert any(
        "maximum odometry-info receive gap" in failure
        for failure in report["failures"]
    )


def test_missing_quality_stream_and_wrong_frames_fail() -> None:
    records = synthetic_records()
    odom = [record for record in records if record["type"] == "odom"]
    for record in odom:
        record["frame_id"] = "wrong_odom"
        record["child_frame_id"] = "wrong_camera"
    report = analyze_records(odom)
    assert report["status"] == "FAIL"
    assert any("odometry-info" in failure for failure in report["failures"])
    assert any("frame_id must be odom" in failure for failure in report["failures"])
    assert any("child_frame_id must be camera_link" in failure for failure in report["failures"])


def test_quaternion_sign_change_is_not_rotation() -> None:
    records = synthetic_records(duration_s=6.0, rate_hz=10.0, drift_m=0.0)
    odom = [record for record in records if record["type"] == "odom"]
    odom[-1]["orientation"] = [0.0, 0.0, 0.0, -1.0]
    report = analyze_records(records, Thresholds(minimum_duration_s=5.0))
    assert report["rotation_drift_deg"] == 0.0
