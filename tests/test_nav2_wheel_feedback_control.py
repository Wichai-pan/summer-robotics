import math

import pytest

from tools.nav2_supervised_base_execute import (
    WheelPoseTracker,
    map_pose_spread,
    validate_rotate_only_feedback,
    wheel_raw_to_body_velocity,
)


def test_measured_forward_wheel_feedback_matches_established_command_scale() -> None:
    # From the 2026-08-23 floor pulse: +/-452 raw was commanded and measured
    # on IDs 7/9, producing about 5 cm in one second.
    vx, vy, wz = wheel_raw_to_body_velocity({7: -452, 8: 0, 9: 452})

    assert vx == pytest.approx(0.0400, abs=0.001)
    assert vy == pytest.approx(0.0, abs=1e-6)
    assert wz == pytest.approx(0.0, abs=1e-6)


def test_tracker_uses_measured_velocity_not_requested_distance() -> None:
    tracker = WheelPoseTracker((1.0, -2.0, 0.0))
    tracker.update({7: 0, 8: 0, 9: 0}, 10.0)
    x, y, yaw = tracker.update({7: -452, 8: 0, 9: 452}, 10.2)

    assert x == pytest.approx(1.0080, abs=0.001)
    assert y == pytest.approx(-2.0, abs=1e-6)
    assert yaw == pytest.approx(0.0, abs=1e-6)


def test_tracker_integrates_measured_rotation() -> None:
    tracker = WheelPoseTracker((0.0, 0.0, 0.0))
    tracker.update({7: 0, 8: 0, 9: 0}, 1.0)
    _x, _y, yaw = tracker.update({7: 500, 8: 500, 9: 500}, 1.2)

    assert yaw == pytest.approx(
        math.degrees(0.05 * 500 * 2 * math.pi / 4096 / 0.125 * 0.2), abs=1e-6
    )


def test_tracker_applies_measured_chassis_yaw_scale() -> None:
    # Floor references on 2026-08-25 showed approximately 120 degrees of
    # symmetric left/right wheel feedback is a 90-degree chassis turn.
    tracker = WheelPoseTracker((0.0, 0.0, 0.0), yaw_scale=0.75)
    tracker.update({7: 0, 8: 0, 9: 0}, 1.0)
    _x, _y, yaw = tracker.update({7: 500, 8: 500, 9: 500}, 1.2)

    expected_unscaled = math.degrees(0.05 * 500 * 2 * math.pi / 4096 / 0.125 * 0.2)
    assert yaw == pytest.approx(0.75 * expected_unscaled, abs=1e-6)


def test_tracker_rejects_unbounded_yaw_scale() -> None:
    with pytest.raises(ValueError, match="yaw scale"):
        WheelPoseTracker((0.0, 0.0, 0.0), yaw_scale=1.01)


def test_wheel_rotate_only_guard_rejects_accumulated_lateral_drift() -> None:
    # Reduced from the 2026-08-24 table-side trace. The wheel-controlled pose
    # began near this anchor but drifted laterally while the command remained
    # rotate-only. The guard must apply before a later path correction can turn
    # the chassis toward furniture.
    anchor = (0.0176, -0.0136)

    assert validate_rotate_only_feedback(anchor, 0.0326, -0.0141, 0.05) < 0.05

    with pytest.raises(RuntimeError, match="base feedback is inconsistent"):
        validate_rotate_only_feedback(anchor, 0.0700, -0.0120, 0.05)


def test_fresh_visual_update_smoothly_corrects_wheel_slip_without_pose_jump() -> None:
    tracker = WheelPoseTracker((0.0, 0.0, 0.0))
    tracker.update({7: 0, 8: 0, 9: 0}, 1.0)
    tracker.update({7: -452, 8: 0, 9: 452}, 1.2)

    disagreement, correction_m, correction_yaw_deg = tracker.correct_toward_visual(
        (0.004, 0.0, 10.0),
        gain=0.5,
        max_position_step_m=0.002,
        max_yaw_step_deg=2.0,
    )

    assert disagreement == pytest.approx(0.004, abs=0.001)
    assert correction_m == pytest.approx(0.002, abs=1e-6)
    assert correction_yaw_deg == pytest.approx(2.0, abs=1e-6)
    assert tracker.x_m == pytest.approx(0.006, abs=0.001)
    assert tracker.yaw_deg == pytest.approx(2.0, abs=1e-6)


def test_visual_correction_rejects_invalid_parameters() -> None:
    tracker = WheelPoseTracker((0.0, 0.0, 0.0))

    with pytest.raises(ValueError, match="gain"):
        tracker.correct_toward_visual(
            (0.0, 0.0, 0.0),
            gain=0.0,
            max_position_step_m=0.01,
            max_yaw_step_deg=1.0,
        )


def test_map_pose_spread_accepts_small_stable_relocalization_window() -> None:
    spread_m, yaw_spread_deg = map_pose_spread(
        [
            (0.100, -0.200, 179.0, 0.0),
            (0.105, -0.198, -179.0, 0.0),
            (0.102, -0.201, -180.0, 0.0),
        ]
    )

    assert spread_m == pytest.approx(math.hypot(0.003, 0.003), abs=1e-6)
    assert yaw_spread_deg == pytest.approx(1.0, abs=1e-6)


def test_map_pose_spread_rejects_empty_window() -> None:
    with pytest.raises(ValueError, match="at least one"):
        map_pose_spread([])


def test_wheel_feedback_rejects_missing_motor() -> None:
    with pytest.raises(RuntimeError, match="wheel feedback IDs"):
        wheel_raw_to_body_velocity({7: 0, 8: 0})
