import math

import pytest

from tools.nav2_supervised_base_execute import (
    WheelPoseTracker,
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
    _x, _y, yaw = tracker.update({7: 500, 8: 500, 9: 500}, 2.0)

    assert yaw == pytest.approx(math.degrees(0.05 * 500 * 2 * math.pi / 4096 / 0.125), abs=1e-6)


def test_wheel_feedback_rejects_missing_motor() -> None:
    with pytest.raises(RuntimeError, match="wheel feedback IDs"):
        wheel_raw_to_body_velocity({7: 0, 8: 0})
