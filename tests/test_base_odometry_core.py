import math

import pytest

from tools.base_keyboard import WHEEL_IDS
from tools.base_odometry_core import (
    BodyVelocity,
    FeedbackFault,
    FeedbackLimits,
    SE2Odometry,
    WheelFeedback,
    body_to_wheel_rad_s,
    wheel_to_body_rad_s,
)
from tools.base_wheel_feedback import FakeWheelFeedbackSource


@pytest.mark.parametrize(
    "body",
    [
        BodyVelocity(0.1, 0.0, 0.0),
        BodyVelocity(0.0, 0.1, 0.0),
        BodyVelocity(0.0, 0.0, 0.5),
        BodyVelocity(0.08, -0.03, -0.4),
    ],
)
def test_forward_inverse_kinematics_round_trip(body: BodyVelocity) -> None:
    recovered = wheel_to_body_rad_s(body_to_wheel_rad_s(body))
    assert recovered.vx_mps == pytest.approx(body.vx_mps)
    assert recovered.vy_mps == pytest.approx(body.vy_mps)
    assert recovered.wz_rad_s == pytest.approx(body.wz_rad_s)


def test_established_motion_signs() -> None:
    forward = body_to_wheel_rad_s(BodyVelocity(0.1, 0, 0))
    lateral = body_to_wheel_rad_s(BodyVelocity(0, 0.1, 0))
    turn = body_to_wheel_rad_s(BodyVelocity(0, 0, 0.5))
    assert forward[0] < 0 < forward[2] and forward[1] == pytest.approx(0)
    assert lateral[1] < 0 < lateral[0] and lateral[2] > 0
    assert all(value > 0 for value in turn)


@pytest.mark.parametrize(
    ("velocity", "expected"),
    [
        (BodyVelocity(0, 0, 0), (0, 0, 0)),
        (BodyVelocity(0.1, 0, 0), (0.1, 0, 0)),
        (BodyVelocity(0, 0.1, 0), (0, 0.1, 0)),
        (BodyVelocity(0, 0, math.pi / 2), (0, 0, math.pi / 2)),
    ],
)
def test_fake_trajectories(velocity: BodyVelocity, expected: tuple[float, float, float]) -> None:
    odom = SE2Odometry()
    for sample in FakeWheelFeedbackSource(velocity, duration_s=1, rate_hz=20).samples():
        pose, _ = odom.update(sample)
    assert pose.x_m == pytest.approx(expected[0], abs=1e-3)
    assert pose.y_m == pytest.approx(expected[1], abs=1e-3)
    assert pose.yaw_rad == pytest.approx(expected[2], abs=1e-3)


def test_irregular_sampling_uses_se2_midpoint_integration() -> None:
    odom = SE2Odometry(FeedbackLimits(max_gap_s=1.0, max_wheel_accel_rad_s2=1000))
    velocity = BodyVelocity(0.2, 0.0, 0.5)
    wheels = dict(zip(WHEEL_IDS, body_to_wheel_rad_s(velocity)))
    for timestamp in (0.0, 0.1, 0.37, 0.9):
        pose, _ = odom.update(WheelFeedback(timestamp, wheels, timestamp))
    assert pose.yaw_rad == pytest.approx(0.45)
    assert math.hypot(pose.x_m, pose.y_m) > 0.17


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_wheel_feedback_fails(bad: float) -> None:
    odom = SE2Odometry()
    with pytest.raises(FeedbackFault):
        odom.update(WheelFeedback(0.0, {7: bad, 8: 0.0, 9: 0.0}, 0.0))


def test_time_gap_reverse_missing_stale_speed_and_acceleration_fail() -> None:
    cases = [
        [WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.0), WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.0)],
        [WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.0), WheelFeedback(0.9, {7: 0, 8: 0, 9: 0}, 0.9)],
        [WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.0), WheelFeedback(1.5, {7: 0, 8: 0, 9: 0}, 1.5)],
        [WheelFeedback(1.0, {7: 0, 8: 0}, 1.0)],
        [WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.2)],
        [WheelFeedback(1.0, {7: 81, 8: 0, 9: 0}, 1.0)],
        [WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.0), WheelFeedback(1.01, {7: 10, 8: 0, 9: 0}, 1.01)],
    ]
    for samples in cases:
        odom = SE2Odometry()
        with pytest.raises(FeedbackFault):
            for sample in samples:
                odom.update(sample)


def test_watchdog_fails_without_or_after_stale_feedback() -> None:
    odom = SE2Odometry(FeedbackLimits(max_gap_s=0.2))
    with pytest.raises(FeedbackFault, match="no wheel feedback"):
        odom.guard.check_watchdog(1.0)
    odom.update(WheelFeedback(1.0, {7: 0, 8: 0, 9: 0}, 1.0))
    odom.guard.check_watchdog(1.19)
    with pytest.raises(FeedbackFault, match="watchdog") as error:
        odom.guard.check_watchdog(1.21)
    assert error.value.safe_stop_required
