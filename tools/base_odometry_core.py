#!/usr/bin/env python3
"""Hardware-free three-wheel kinematics, feedback checks, and SE(2) odometry."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

try:
    from .base_keyboard import (
        BASE_RADIUS_M,
        WHEEL_IDS,
        WHEEL_MOUNT_ANGLES_DEG,
        WHEEL_RADIUS_M,
    )
except ImportError:
    from base_keyboard import (  # type: ignore
        BASE_RADIUS_M,
        WHEEL_IDS,
        WHEEL_MOUNT_ANGLES_DEG,
        WHEEL_RADIUS_M,
    )


class FeedbackFault(RuntimeError):
    """A feedback fault that requires the owning live session to stop motion."""

    safe_stop_required = True


@dataclass(frozen=True)
class BodyVelocity:
    vx_mps: float
    vy_mps: float
    wz_rad_s: float


@dataclass(frozen=True)
class WheelFeedback:
    monotonic_s: float
    velocity_rad_s: Mapping[int, float]
    received_monotonic_s: float | None = None
    raw_position: Mapping[int, int] | None = None
    raw_velocity: Mapping[int, int] | None = None
    status: Mapping[int, int] | None = None
    moving: Mapping[int, int] | None = None
    velocity_unit_factor_raw: Mapping[int, int] | None = None


@dataclass(frozen=True)
class Pose2D:
    x_m: float = 0.0
    y_m: float = 0.0
    yaw_rad: float = 0.0


@dataclass(frozen=True)
class FeedbackLimits:
    max_gap_s: float = 0.25
    max_age_s: float = 0.10
    max_wheel_speed_rad_s: float = 80.0
    max_wheel_accel_rad_s2: float = 300.0


def _finite(values: Sequence[float], label: str) -> None:
    if not all(math.isfinite(float(value)) for value in values):
        raise FeedbackFault(f"{label} contains NaN or Inf")


def body_to_wheel_rad_s(
    velocity: BodyVelocity,
    wheel_radius_m: float = WHEEL_RADIUS_M,
    base_radius_m: float = BASE_RADIUS_M,
) -> tuple[float, float, float]:
    """Apply the exact geometry and wheel order used by ``base_keyboard.py``."""
    _finite((velocity.vx_mps, velocity.vy_mps, velocity.wz_rad_s), "body velocity")
    if wheel_radius_m <= 0 or base_radius_m <= 0:
        raise ValueError("wheel and base radii must be positive")
    angles = [math.radians(value - 90.0) for value in WHEEL_MOUNT_ANGLES_DEG]
    return tuple(
        (
            math.cos(angle) * velocity.vx_mps
            + math.sin(angle) * velocity.vy_mps
            + base_radius_m * velocity.wz_rad_s
        )
        / wheel_radius_m
        for angle in angles
    )


def wheel_to_body_rad_s(
    wheel_rad_s: Sequence[float],
    wheel_radius_m: float = WHEEL_RADIUS_M,
    base_radius_m: float = BASE_RADIUS_M,
) -> BodyVelocity:
    """Invert the established symmetric three-wheel omni kinematics."""
    if len(wheel_rad_s) != 3:
        raise FeedbackFault("exactly three wheel velocities are required")
    _finite(wheel_rad_s, "wheel velocity")
    if wheel_radius_m <= 0 or base_radius_m <= 0:
        raise ValueError("wheel and base radii must be positive")

    linear = [float(value) * wheel_radius_m for value in wheel_rad_s]
    angles = [math.radians(value - 90.0) for value in WHEEL_MOUNT_ANGLES_DEG]
    # For equally spaced wheels, M^T M = diag(3/2, 3/2, 3 L^2).
    vx = (2.0 / 3.0) * sum(math.cos(a) * v for a, v in zip(angles, linear))
    vy = (2.0 / 3.0) * sum(math.sin(a) * v for a, v in zip(angles, linear))
    wz = sum(linear) / (3.0 * base_radius_m)
    return BodyVelocity(vx, vy, wz)


class FeedbackGuard:
    def __init__(self, limits: FeedbackLimits = FeedbackLimits()) -> None:
        self.limits = limits
        self._previous: WheelFeedback | None = None

    def validate(self, sample: WheelFeedback) -> tuple[float, float, float]:
        ids = set(sample.velocity_rad_s)
        if ids != set(WHEEL_IDS):
            raise FeedbackFault(f"wheel IDs must be exactly {WHEEL_IDS}; got {sorted(ids)}")
        ordered = tuple(float(sample.velocity_rad_s[motor_id]) for motor_id in WHEEL_IDS)
        _finite((sample.monotonic_s, *ordered), "wheel feedback")
        if sample.received_monotonic_s is not None:
            _finite((sample.received_monotonic_s,), "receive timestamp")
            age = sample.received_monotonic_s - sample.monotonic_s
            if age < 0 or age > self.limits.max_age_s:
                raise FeedbackFault(f"stale wheel feedback age {age:.3f}s")
        if max(abs(value) for value in ordered) > self.limits.max_wheel_speed_rad_s:
            raise FeedbackFault("wheel velocity exceeds configured limit")

        if self._previous is not None:
            dt = sample.monotonic_s - self._previous.monotonic_s
            if dt <= 0:
                raise FeedbackFault("wheel feedback timestamp is not strictly monotonic")
            if dt > self.limits.max_gap_s:
                raise FeedbackFault(f"wheel feedback gap {dt:.3f}s exceeds limit")
            previous = tuple(
                float(self._previous.velocity_rad_s[motor_id]) for motor_id in WHEEL_IDS
            )
            acceleration = max(abs(a - b) / dt for a, b in zip(ordered, previous))
            if acceleration > self.limits.max_wheel_accel_rad_s2:
                raise FeedbackFault("wheel acceleration jump exceeds configured limit")
        self._previous = sample
        return ordered

    def check_watchdog(self, now_monotonic_s: float) -> None:
        """Fail even when no next sample arrives to expose a gap."""
        if self._previous is None:
            raise FeedbackFault("no wheel feedback has been received")
        age = now_monotonic_s - self._previous.monotonic_s
        if not math.isfinite(age) or age < 0 or age > self.limits.max_gap_s:
            raise FeedbackFault(f"wheel feedback watchdog age {age:.3f}s exceeds limit")


class SE2Odometry:
    def __init__(self, limits: FeedbackLimits = FeedbackLimits()) -> None:
        self.pose = Pose2D()
        self.guard = FeedbackGuard(limits)
        self._last_s: float | None = None

    def update(self, sample: WheelFeedback) -> tuple[Pose2D, BodyVelocity]:
        wheels = self.guard.validate(sample)
        velocity = wheel_to_body_rad_s(wheels)
        if self._last_s is None:
            self._last_s = sample.monotonic_s
            return self.pose, velocity
        dt = sample.monotonic_s - self._last_s
        mid_yaw = self.pose.yaw_rad + 0.5 * velocity.wz_rad_s * dt
        self.pose = Pose2D(
            self.pose.x_m
            + (math.cos(mid_yaw) * velocity.vx_mps - math.sin(mid_yaw) * velocity.vy_mps) * dt,
            self.pose.y_m
            + (math.sin(mid_yaw) * velocity.vx_mps + math.cos(mid_yaw) * velocity.vy_mps) * dt,
            math.atan2(
                math.sin(self.pose.yaw_rad + velocity.wz_rad_s * dt),
                math.cos(self.pose.yaw_rad + velocity.wz_rad_s * dt),
            ),
        )
        self._last_s = sample.monotonic_s
        return self.pose, velocity
