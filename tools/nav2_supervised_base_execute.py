#!/usr/bin/env python3
"""Execute one short Nav2 plan with the XLeRobot base under strict guards.

This is deliberately a supervised *first-motion* bridge, not a general
autonomous navigation stack. It consumes a path already produced by Nav2,
reads live RGB-D odometry composed with ``map -> odom``, and sends only bounded velocity-mode
commands to white-board wheel IDs 7/8/9. Any transport, TF freshness, progress,
time, path-length, or operator interruption issue immediately sends zero wheel
velocity and releases torque.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

# Match the existing base_keyboard.py transport constants. Keeping these small
# constants local lets --dry-run validate only a Nav2 path without importing a
# serial package or opening a board.
WHEEL_IDS = [7, 8, 9]
GOAL_VEL = 46
TORQUE = 40
PRESENT_VELOCITY = 58
LOOP_HZ = 5.0
STOP_BUS_SETTLE_S = 0.2
STOP_READBACK_PERIOD_S = 0.5
WHEEL_RADIUS_M = 0.05
BASE_RADIUS_M = 0.125
RAW_TO_RAD_S = 2.0 * math.pi / 4096.0
WHEEL_ANGLES_RAD = tuple(math.radians(angle - 90.0) for angle in (240.0, 0.0, 120.0))


def wrap_degrees(value: float) -> float:
    """Return the shortest signed angular difference in [-180, 180)."""
    return (value + 180.0) % 360.0 - 180.0


def yaw_from_quaternion(quaternion: Any) -> float:
    x = float(quaternion.x)
    y = float(quaternion.y)
    z = float(quaternion.z)
    w = float(quaternion.w)
    yaw = math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))
    if not math.isfinite(yaw):
        raise ValueError("TF quaternion produced a non-finite yaw")
    return yaw


def path_points(path_json: Path) -> list[tuple[float, float, float]]:
    payload = json.loads(path_json.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise ValueError("Nav2 path JSON does not report PASS")
    points = payload.get("poses_map_xy_yaw_deg")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("Nav2 path JSON needs at least two poses_map_xy_yaw_deg entries")
    parsed: list[tuple[float, float, float]] = []
    for index, item in enumerate(points):
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError(f"path point {index} is malformed")
        point = tuple(float(value) for value in item)
        if not all(math.isfinite(value) for value in point):
            raise ValueError(f"path point {index} is non-finite")
        parsed.append(point)
    return parsed


def polyline_length(points: list[tuple[float, float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def nearest_forward_waypoint(
    points: list[tuple[float, float, float]], current_x: float, current_y: float, start_index: int
) -> int:
    """Advance monotonically to the nearest remaining waypoint."""
    distances = [math.hypot(point[0] - current_x, point[1] - current_y) for point in points[start_index:]]
    return start_index + min(range(len(distances)), key=distances.__getitem__)


def advance_waypoint_index(
    points: list[tuple[float, float, float]],
    current_x: float,
    current_y: float,
    start_index: int,
    position_tolerance_m: float,
    *,
    allow_translation_progress: bool,
) -> int:
    """Advance only when the pose follows a commanded translation."""
    if not allow_translation_progress:
        return start_index
    waypoint_index = nearest_forward_waypoint(points, current_x, current_y, start_index)
    while waypoint_index < len(points) - 1 and math.hypot(
        points[waypoint_index][0] - current_x, points[waypoint_index][1] - current_y
    ) < position_tolerance_m:
        waypoint_index += 1
    return waypoint_index


def lookahead_waypoint_index(
    points: list[tuple[float, float, float]],
    current_x: float,
    current_y: float,
    start_index: int,
    lookahead_m: float,
) -> int:
    """Return an ordered path point at least ``lookahead_m`` ahead of the base.

    Nav2 grid paths often contain an opening point only a few centimetres from
    the localized start pose. Steering exactly toward such a point can create
    a needless large turn immediately followed by an opposite correction for
    the main route.  This is a pure-pursuit-style target selection: retain the
    ordered path index for progress, but steer toward a short distance ahead.
    """
    if not 0 <= start_index < len(points):
        raise ValueError(f"invalid path start index {start_index}")
    if not math.isfinite(lookahead_m) or lookahead_m <= 0.0:
        raise ValueError("path lookahead must be finite and positive")
    previous_x, previous_y = current_x, current_y
    accumulated_m = 0.0
    for index in range(start_index, len(points)):
        point_x, point_y, _ = points[index]
        accumulated_m += math.hypot(point_x - previous_x, point_y - previous_y)
        if accumulated_m >= lookahead_m:
            return index
        previous_x, previous_y = point_x, point_y
    return len(points) - 1


def path_alignment_progress(
    goal_distance_m: float,
    best_goal_distance_m: float,
    heading_error_deg: float,
    best_heading_error_deg: float,
    *,
    feedback_mode: str,
) -> tuple[bool, float, float]:
    """Accept only progress consistent with the command that produced it."""
    if feedback_mode not in {"stopped", "rotate", "translate"}:
        raise ValueError(f"unknown feedback mode: {feedback_mode}")
    distance_progress = feedback_mode == "translate" and goal_distance_m + 0.015 < best_goal_distance_m
    heading_error_abs = abs(heading_error_deg)
    heading_progress = feedback_mode == "rotate" and heading_error_abs + 2.0 < best_heading_error_deg
    return (
        distance_progress or heading_progress,
        min(best_goal_distance_m, goal_distance_m) if distance_progress else best_goal_distance_m,
        min(best_heading_error_deg, heading_error_abs) if heading_progress else best_heading_error_deg,
    )


def rotation_progress_baseline(
    previous_feedback_mode: str,
    next_feedback_mode: str,
    heading_error_deg: float,
    previous_best_heading_error_deg: float,
) -> float:
    """Start each distinct rotation with its own heading-progress baseline."""
    if next_feedback_mode == "rotate" and previous_feedback_mode != "rotate":
        return abs(heading_error_deg)
    return previous_best_heading_error_deg


def validate_rotate_only_feedback(
    anchor_xy: tuple[float, float],
    current_x: float,
    current_y: float,
    maximum_translation_m: float,
) -> float:
    """Reject any control-pose translation produced by an in-place turn.

    RGB-D-only control originally used this check to reject false camera
    translation. Wheel-feedback control needs the same physical invariant: a
    rotate-only command must not be allowed to accumulate a large XY motion,
    even if that motion comes from wheel slip or inconsistent wheel feedback.
    """
    translation_m = math.hypot(current_x - anchor_xy[0], current_y - anchor_xy[1])
    if translation_m > maximum_translation_m:
        raise RuntimeError(
            "rotate-only control pose reported "
            f"{translation_m:.3f} m translation; base feedback is inconsistent"
        )
    return translation_m


def map_delta_to_body_velocity(
    delta_x_m: float, delta_y_m: float, yaw_deg: float, speed_mps: float
) -> tuple[float, float]:
    """Map-frame displacement to holonomic base-frame translation without yaw."""
    distance_m = math.hypot(delta_x_m, delta_y_m)
    if not all(math.isfinite(value) for value in (delta_x_m, delta_y_m, yaw_deg, speed_mps)):
        raise ValueError("dock velocity inputs must be finite")
    if distance_m <= 0.0 or speed_mps <= 0.0:
        return 0.0, 0.0
    yaw_rad = math.radians(yaw_deg)
    map_vx = speed_mps * delta_x_m / distance_m
    map_vy = speed_mps * delta_y_m / distance_m
    return (
        math.cos(yaw_rad) * map_vx + math.sin(yaw_rad) * map_vy,
        -math.sin(yaw_rad) * map_vx + math.cos(yaw_rad) * map_vy,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", help="white-board serial override")
    parser.add_argument("--max-planned-path-m", type=float, default=0.30)
    parser.add_argument("--max-runtime-s", type=float, default=20.0)
    parser.add_argument("--max-linear-mps", type=float, default=0.04)
    parser.add_argument("--max-angular-deg-s", type=float, default=12.0)
    parser.add_argument("--position-tolerance-m", type=float, default=0.07)
    parser.add_argument("--yaw-tolerance-deg", type=float, default=8.0)
    parser.add_argument("--max-start-error-m", type=float, default=0.12)
    parser.add_argument("--max-tf-stale-s", type=float, default=1.25)
    parser.add_argument("--max-tracked-travel-m", type=float, default=0.40)
    parser.add_argument("--progress-timeout-s", type=float, default=5.0)
    parser.add_argument(
        "--path-lookahead-m",
        type=float,
        default=0.10,
        help="ordered Nav2 path distance used for the steering target",
    )
    parser.add_argument(
        "--control-pose-source",
        choices=("rgbd", "wheel"),
        default="rgbd",
        help=(
            "rgbd uses the legacy camera-only pose; wheel anchors measured wheel feedback "
            "at the freshly localized map pose for short supervised motion"
        ),
    )
    parser.add_argument(
        "--max-wheel-visual-disagreement-m",
        type=float,
        default=0.20,
        help="in wheel mode, abort translating if RGB-D and wheel poses diverge farther than this",
    )
    parser.add_argument(
        "--wheel-visual-correction-gain",
        type=float,
        default=0.15,
        help="fresh RGB-D blend gain applied to wheel pose during commanded translation",
    )
    parser.add_argument(
        "--max-wheel-visual-correction-step-m",
        type=float,
        default=0.012,
        help="maximum map-frame position correction from one fresh RGB-D update",
    )
    parser.add_argument(
        "--max-wheel-visual-yaw-correction-deg",
        type=float,
        default=2.0,
        help="maximum heading correction from one fresh RGB-D update",
    )
    parser.add_argument(
        "--wheel-yaw-scale",
        type=float,
        default=0.75,
        help=(
            "physical chassis yaw per wheel-velocity-integrated yaw; calibrated "
            "from the 2026-08-25 left/right 120-degree feedback ~= 90-degree floor turn"
        ),
    )
    parser.add_argument(
        "--wheel-visual-policy",
        choices=("bounded", "liveness"),
        default="bounded",
        help=(
            "bounded blends/re-localizes from fresh RGB-D during translation; "
            "liveness still requires a fresh RGB-D stream and initial map pose, "
            "but logs rather than applies unstable old-map translation updates"
        ),
    )
    parser.add_argument(
        "--wheel-visual-relocalize-m",
        type=float,
        default=0.12,
        help="pause and re-anchor the wheel pose if fresh map-frame vision disagrees by this far",
    )
    parser.add_argument(
        "--max-wheel-visual-relocalizations",
        type=int,
        default=1,
        help="maximum bounded map-pose re-anchors during one supervised leg",
    )
    parser.add_argument(
        "--relocalization-settle-s",
        type=float,
        default=3.0,
        help="zero-velocity settling time before accepting a map-pose re-anchor",
    )
    parser.add_argument(
        "--relocalization-max-spread-m",
        type=float,
        default=0.04,
        help="maximum XY spread of map poses accepted after a re-anchor pause",
    )
    parser.add_argument(
        "--relocalization-max-yaw-spread-deg",
        type=float,
        default=6.0,
        help="maximum yaw spread of map poses accepted after a re-anchor pause",
    )
    parser.add_argument(
        "--max-rotate-translation-m",
        type=float,
        default=0.05,
        help="abort if rotate-only feedback translates base_link farther than this",
    )
    parser.add_argument(
        "--brake-s",
        type=float,
        default=0.8,
        help="active zero-velocity braking time before wheel torque is released",
    )
    parser.add_argument(
        "--dock-entry-distance-m",
        type=float,
        default=0.0,
        help=(
            "explicit table-docking mode: align goal yaw at this distance, then translate "
            "holonomically with no further yaw commands; 0 disables docking mode"
        ),
    )
    parser.add_argument(
        "--dock-yaw-align-tolerance-deg",
        type=float,
        default=6.0,
        help="maximum yaw error allowed while translating in explicit docking mode",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate plan only; never open serial or ROS TF")
    return parser.parse_args()


def validate_limits(args: argparse.Namespace) -> None:
    values = (
        args.max_planned_path_m,
        args.max_runtime_s,
        args.max_linear_mps,
        args.max_angular_deg_s,
        args.position_tolerance_m,
        args.yaw_tolerance_deg,
        args.max_start_error_m,
        args.max_tf_stale_s,
        args.max_tracked_travel_m,
        args.progress_timeout_s,
        args.path_lookahead_m,
        args.max_rotate_translation_m,
        args.max_wheel_visual_disagreement_m,
        args.wheel_visual_correction_gain,
        args.max_wheel_visual_correction_step_m,
        args.max_wheel_visual_yaw_correction_deg,
        args.wheel_yaw_scale,
        args.wheel_visual_relocalize_m,
        args.relocalization_settle_s,
        args.relocalization_max_spread_m,
        args.relocalization_max_yaw_spread_deg,
        args.brake_s,
        args.dock_yaw_align_tolerance_deg,
    )
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("all execution limits must be finite and > 0")
    if args.max_linear_mps > 0.08 or args.max_angular_deg_s > 20.0:
        raise ValueError("first-motion speed caps are fixed at <=0.08 m/s and <=20 deg/s")
    if args.wheel_visual_correction_gain > 1.0:
        raise ValueError("wheel/RGB-D correction gain must be <= 1")
    if not 0.5 <= args.wheel_yaw_scale <= 1.0:
        raise ValueError("wheel yaw scale must be in [0.5, 1.0]")
    if args.wheel_visual_relocalize_m >= args.max_wheel_visual_disagreement_m:
        raise ValueError("wheel/RGB-D re-localization threshold must be below the hard disagreement stop")
    if args.max_wheel_visual_relocalizations < 0:
        raise ValueError("maximum wheel/RGB-D re-localizations must be >= 0")
    if args.brake_s > 1.0:
        raise ValueError("first-motion active braking is capped at <=1.0 s")
    if args.dock_entry_distance_m and args.dock_entry_distance_m <= args.position_tolerance_m:
        raise ValueError("dock entry distance must exceed position tolerance when docking mode is enabled")
    if not math.isfinite(args.dock_entry_distance_m) or args.dock_entry_distance_m < 0.0:
        raise ValueError("dock entry distance must be finite and >= 0")


def compose_map_pose(
    map_to_odom: Any, odom_x: float, odom_y: float, odom_yaw_deg: float
) -> tuple[float, float, float]:
    """Compose a current odom pose with RTAB-Map's map -> odom correction."""
    translation = map_to_odom.transform.translation
    map_to_odom_yaw = yaw_from_quaternion(map_to_odom.transform.rotation)
    yaw_rad = math.radians(map_to_odom_yaw)
    return (
        float(translation.x) + math.cos(yaw_rad) * odom_x - math.sin(yaw_rad) * odom_y,
        float(translation.y) + math.sin(yaw_rad) * odom_x + math.cos(yaw_rad) * odom_y,
        wrap_degrees(map_to_odom_yaw + odom_yaw_deg),
    )


def decode_signed_magnitude(value: int) -> int:
    """Decode the STS3215 velocity register's sign-magnitude representation."""
    return -(value & 0x7FFF) if value & 0x8000 else value


def wheel_raw_to_body_velocity(raw_by_id: dict[int, int]) -> tuple[float, float, float]:
    """Invert the established three-wheel command geometry using measured raw velocity.

    ``body_to_wheel_raw()`` uses 4096 encoder ticks per wheel revolution. The
    same raw scale is confirmed by the 2026-08-23 1-second forward pulse: the
    measured wheel feedback tracked the +/-452 raw command and the chassis
    moved about 5 cm. This is intentionally a short-range feedback estimate,
    not a replacement for global map localization.
    """
    if set(raw_by_id) != set(WHEEL_IDS):
        raise RuntimeError(f"wheel feedback IDs must be {WHEEL_IDS}; got {sorted(raw_by_id)}")
    wheel_rad_s = [float(raw_by_id[motor_id]) * RAW_TO_RAD_S for motor_id in WHEEL_IDS]
    if not all(math.isfinite(value) for value in wheel_rad_s):
        raise RuntimeError("wheel feedback contains a non-finite velocity")
    linear = [WHEEL_RADIUS_M * value for value in wheel_rad_s]
    vx = (2.0 / 3.0) * sum(math.cos(angle) * value for angle, value in zip(WHEEL_ANGLES_RAD, linear))
    vy = (2.0 / 3.0) * sum(math.sin(angle) * value for angle, value in zip(WHEEL_ANGLES_RAD, linear))
    wz_rad_s = sum(linear) / (3.0 * BASE_RADIUS_M)
    return vx, vy, wz_rad_s


class WheelPoseTracker:
    """Integrate actual wheel feedback from a freshly localized map-frame anchor."""

    def __init__(
        self,
        anchor_map_pose: tuple[float, float, float],
        *,
        yaw_scale: float = 1.0,
    ) -> None:
        if not math.isfinite(yaw_scale) or not 0.5 <= yaw_scale <= 1.0:
            raise ValueError("wheel yaw scale must be in [0.5, 1.0]")
        self.x_m, self.y_m, self.yaw_deg = anchor_map_pose
        self.yaw_scale = yaw_scale
        self._last_s: float | None = None

    def update(self, raw_by_id: dict[int, int], now_s: float) -> tuple[float, float, float]:
        if not math.isfinite(now_s):
            raise RuntimeError("wheel feedback time is non-finite")
        vx, vy, wz_rad_s = wheel_raw_to_body_velocity(raw_by_id)
        if self._last_s is None:
            self._last_s = now_s
            return self.x_m, self.y_m, self.yaw_deg
        dt = now_s - self._last_s
        if not 0.0 < dt <= 0.35:
            raise RuntimeError(f"wheel feedback gap {dt:.3f} s is outside (0, 0.35]")
        yaw_rad = math.radians(self.yaw_deg)
        scaled_wz_rad_s = self.yaw_scale * wz_rad_s
        mid_yaw = yaw_rad + 0.5 * scaled_wz_rad_s * dt
        self.x_m += (math.cos(mid_yaw) * vx - math.sin(mid_yaw) * vy) * dt
        self.y_m += (math.sin(mid_yaw) * vx + math.cos(mid_yaw) * vy) * dt
        self.yaw_deg = wrap_degrees(math.degrees(yaw_rad + scaled_wz_rad_s * dt))
        self._last_s = now_s
        return self.x_m, self.y_m, self.yaw_deg

    def correct_toward_visual(
        self,
        visual_pose: tuple[float, float, float],
        *,
        gain: float,
        max_position_step_m: float,
        max_yaw_step_deg: float,
    ) -> tuple[float, float, float]:
        """Blend one fresh RGB-D update into the wheel-predicted map pose.

        Motor velocity measures shaft rotation, so floor slip can drift a
        wheel-only pose. RGB-D can correct that drift but is visibly noisy in
        this room. Each fresh update is therefore bounded; it never replaces
        the control pose in one jump. The result is raw disagreement, applied
        translation and applied yaw correction.
        """
        if not 0.0 < gain <= 1.0:
            raise ValueError("visual correction gain must be in (0, 1]")
        if not math.isfinite(max_position_step_m) or max_position_step_m <= 0.0:
            raise ValueError("maximum visual position correction must be positive")
        if not math.isfinite(max_yaw_step_deg) or max_yaw_step_deg <= 0.0:
            raise ValueError("maximum visual yaw correction must be positive")
        visual_x, visual_y, visual_yaw = visual_pose
        if not all(math.isfinite(value) for value in visual_pose):
            raise RuntimeError("visual correction pose is non-finite")
        dx = visual_x - self.x_m
        dy = visual_y - self.y_m
        raw_disagreement_m = math.hypot(dx, dy)
        applied_m = min(max_position_step_m, gain * raw_disagreement_m)
        if raw_disagreement_m > 0.0:
            self.x_m += dx * applied_m / raw_disagreement_m
            self.y_m += dy * applied_m / raw_disagreement_m
        yaw_innovation_deg = wrap_degrees(visual_yaw - self.yaw_deg)
        applied_yaw_deg = max(
            -max_yaw_step_deg,
            min(max_yaw_step_deg, gain * yaw_innovation_deg),
        )
        self.yaw_deg = wrap_degrees(self.yaw_deg + applied_yaw_deg)
        return raw_disagreement_m, applied_m, applied_yaw_deg


def map_pose_spread(
    poses: list[tuple[float, float, float, float]],
) -> tuple[float, float]:
    """Return maximum XY/yaw deviation from the newest map-frame pose."""
    if not poses:
        raise ValueError("at least one map pose is required")
    anchor_x, anchor_y, anchor_yaw, _age_s = poses[-1]
    return (
        max(math.hypot(x - anchor_x, y - anchor_y) for x, y, _yaw, _age in poses),
        max(abs(wrap_degrees(yaw - anchor_yaw)) for _x, _y, yaw, _age in poses),
    )


def read_wheel_velocity_raw(
    packet: Any,
    port_handler: Any,
    communication_success: int,
    *,
    retries: int = 3,
    retry_delay_s: float = 0.03,
    sleep: Any = time.sleep,
) -> dict[int, int]:
    """Read all whitelisted wheel velocities with a short bounded retry.

    The white-board bus has produced isolated -6/-7 replies followed by clean
    reads. One bad telemetry packet must not cancel a whole localized demo,
    but motion still fails closed if any wheel misses every retry.
    """
    if retries < 1:
        raise ValueError("wheel velocity read retries must be positive")
    values: dict[int, int] = {}
    for motor_id in WHEEL_IDS:
        last_communication = None
        last_packet_error = None
        for attempt in range(1, retries + 1):
            value, communication, packet_error = packet.read2ByteTxRx(
                port_handler, motor_id, PRESENT_VELOCITY
            )
            last_communication = communication
            last_packet_error = packet_error
            if communication == communication_success and packet_error == 0:
                values[motor_id] = decode_signed_magnitude(int(value))
                break
            if attempt < retries:
                sleep(retry_delay_s)
        else:
            raise RuntimeError(
                f"read measured wheel velocity failed for motor {motor_id} "
                f"after {retries} attempts: communication={last_communication}, "
                f"packet_error={last_packet_error}"
            )
    return values


class LiveRgbdOdom:
    """Use received RGB-D odometry, rather than a potentially stale TF stamp.

    During the operator's MOVE confirmation the single-threaded ROS callback
    queue cannot be serviced. A TF lookup immediately afterwards may therefore
    return a queued, older ``odom -> base_link`` transform although fresh odom
    messages are arriving. The received odometry callback is the actual
    liveness signal; map-frame tracking still uses the latest ``map -> odom``
    correction from TF.
    """

    def __init__(self, node: Any, odometry_type: Any) -> None:
        self.count = 0
        self.last_receive_monotonic_s: float | None = None
        self.odom_pose: tuple[float, float, float] | None = None
        self._subscription = node.create_subscription(odometry_type, "/rtabmap/odom", self._callback, 20)

    def _callback(self, message: Any) -> None:
        position = message.pose.pose.position
        orientation = message.pose.pose.orientation
        try:
            pose = (float(position.x), float(position.y), yaw_from_quaternion(orientation))
        except (TypeError, ValueError):
            return
        if not all(math.isfinite(value) for value in pose):
            return
        self.odom_pose = pose
        self.last_receive_monotonic_s = time.monotonic()
        self.count += 1

    def map_pose(self, tf_buffer: Any) -> tuple[float, float, float, float]:
        from rclpy.time import Time

        if self.odom_pose is None or self.last_receive_monotonic_s is None:
            raise RuntimeError("no RGB-D odometry message received")
        map_to_odom = tf_buffer.lookup_transform("map", "odom", Time())
        x, y, yaw = compose_map_pose(map_to_odom, *self.odom_pose)
        return x, y, yaw, max(0.0, time.monotonic() - self.last_receive_monotonic_s)


def live_pose(tf_buffer: Any, odom: LiveRgbdOdom) -> tuple[float, float, float, float]:
    return odom.map_pose(tf_buffer)


def settle_map_relocalization(
    node: Any,
    tf_buffer: Any,
    odom: LiveRgbdOdom,
    *,
    settle_s: float,
    max_spread_m: float,
    max_yaw_spread_deg: float,
    max_tf_stale_s: float,
) -> tuple[tuple[float, float, float, float], dict[str, float]]:
    """Hold zero velocity and accept a fresh, locally stable map pose.

    This does not claim to create a new RTAB-Map loop closure. It ensures the
    controller resumes from a recent ``map -> odom + RGB-D odom`` estimate,
    rather than retaining a wheel-only pose after wheel/ground slip. A noisy
    or stale observation fails closed, leaving the final shutdown path to
    release the wheels.
    """
    import rclpy

    deadline = time.monotonic() + settle_s
    poses: list[tuple[float, float, float, float]] = []
    last_count = -1
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        try:
            candidate = live_pose(tf_buffer, odom)
        except Exception:
            continue
        if candidate[3] > max_tf_stale_s or odom.count == last_count:
            continue
        poses.append(candidate)
        last_count = odom.count
    if len(poses) < 3:
        raise RuntimeError("map re-localization received fewer than three fresh RGB-D poses")
    spread_m, yaw_spread_deg = map_pose_spread(poses)
    if spread_m > max_spread_m or yaw_spread_deg > max_yaw_spread_deg:
        raise RuntimeError(
            "map re-localization was not stable: "
            f"spread={spread_m:.3f} m/{yaw_spread_deg:.1f} deg, "
            f"allowed={max_spread_m:.3f} m/{max_yaw_spread_deg:.1f} deg"
        )
    return poses[-1], {
        "samples": float(len(poses)),
        "spread_m": spread_m,
        "yaw_spread_deg": yaw_spread_deg,
    }


def zero_and_release(packet: Any, port_handler: Any, communication_success: int) -> list[str]:
    errors: list[str] = []
    for motor_id in WHEEL_IDS:
        try:
            communication = packet.write2ByteTxOnly(port_handler, motor_id, GOAL_VEL, 0)
            if communication != communication_success:
                errors.append(f"zero velocity failed for motor {motor_id}: communication={communication}")
        except Exception as exc:  # best effort during emergency shutdown
            errors.append(f"zero velocity failed for motor {motor_id}: {exc}")
        try:
            communication = packet.write1ByteTxOnly(port_handler, motor_id, TORQUE, 0)
            if communication != communication_success:
                errors.append(f"disable torque failed for motor {motor_id}: communication={communication}")
        except Exception as exc:
            errors.append(f"disable torque failed for motor {motor_id}: {exc}")
    try:
        port_handler.closePort()
    except Exception as exc:
        errors.append(f"serial close failed: {exc}")
    return errors


def write_and_verify_byte(
    packet: Any,
    port_handler: Any,
    motor_id: int,
    address: int,
    value: int,
    communication_success: int,
    label: str,
    retries: int = 3,
) -> str | None:
    """Write one byte without requesting an ACK, then verify it separately.

    STS writes can take effect even when their immediate status packet times
    out. A Tx-only write avoids coupling the safety action to that ACK; the
    following delayed read remains the independent proof required for stop.
    """
    last_error = "unknown response"
    for _ in range(retries):
        try:
            communication = packet.write1ByteTxOnly(port_handler, motor_id, address, value)
        except Exception as exc:
            last_error = f"write raised {type(exc).__name__}: {exc}"
            time.sleep(0.1)
            continue
        if communication != communication_success:
            last_error = f"write communication={communication}"
            time.sleep(0.1)
            continue
        time.sleep(0.05)
        try:
            observed, communication, packet_error = packet.read1ByteTxRx(
                port_handler, motor_id, address
            )
        except Exception as exc:
            last_error = f"read raised {type(exc).__name__}: {exc}"
            time.sleep(0.1)
            continue
        if communication == communication_success and packet_error == 0 and int(observed) == value:
            return None
        last_error = (
            f"read value={observed}, communication={communication}, packet_error={packet_error}"
        )
        time.sleep(0.1)
    return f"{label} ID {motor_id} failed after {retries} attempts: {last_error}"


def brake_and_verify_release(
    packet: Any,
    port_handler: Any,
    command_writer: Any,
    communication_success: int,
    brake_s: float,
    *,
    write_zero: Any,
    read_wheels: Any,
    stop_readback_confirmed: Any,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> tuple[dict[str, Any], list[str]]:
    """Attempt the complete stop transaction without abandoning later wheels."""
    report: dict[str, Any] = {
        "attempted": True,
        "active_samples": [],
        "torque_off_samples": [],
    }
    errors: list[str] = []
    brake_deadline = monotonic() + brake_s
    while monotonic() < brake_deadline:
        try:
            write_zero(command_writer, port_handler, [0, 0, 0], communication_success)
        except Exception as exc:
            errors.append(f"active zero velocity failed: {exc}")
        report["active_samples"].append(
            {"phase": "brake_zero_command", "time_monotonic_s": monotonic()}
        )
        sleep(0.1)

    sleep(STOP_BUS_SETTLE_S)
    for motor_id in WHEEL_IDS:
        error = write_and_verify_byte(
            packet,
            port_handler,
            motor_id,
            TORQUE,
            0,
            communication_success,
            "disable torque",
        )
        if error is not None:
            errors.append(error)
    sleep(STOP_BUS_SETTLE_S)
    for _ in range(3):
        try:
            report["torque_off_samples"].append(
                {"phase": "torque_off_observe", **read_wheels(packet, port_handler)}
            )
        except Exception as exc:
            errors.append(f"wheel stop read-back failed: {exc}")
            report["torque_off_samples"].append(
                {"phase": "torque_off_observe", "read_error": str(exc)}
            )
        sleep(STOP_READBACK_PERIOD_S)
    samples = [*report["active_samples"], *report["torque_off_samples"]]
    try:
        report["stop_readback_confirmed"] = bool(stop_readback_confirmed(samples))
    except Exception as exc:
        report["stop_readback_confirmed"] = False
        errors.append(f"wheel stop confirmation failed: {exc}")
    if not report["stop_readback_confirmed"]:
        errors.append("wheel stop read-back was not confirmed")
    return report, errors


def main() -> int:
    args = parse_args()
    validate_limits(args)
    points = path_points(args.path_json)
    plan_length_m = polyline_length(points)
    if plan_length_m > args.max_planned_path_m:
        raise SystemExit(
            f"refusing path length {plan_length_m:.3f} m; first-motion cap is {args.max_planned_path_m:.3f} m"
        )
    summary = {
        "path_json": str(args.path_json),
        "planned_path_length_m": plan_length_m,
        "goal_map_xy_yaw_deg": list(points[-1]),
        "limits": {
            "max_runtime_s": args.max_runtime_s,
            "max_linear_mps": args.max_linear_mps,
            "max_angular_deg_s": args.max_angular_deg_s,
            "max_tracked_travel_m": args.max_tracked_travel_m,
            "max_rotate_translation_m": args.max_rotate_translation_m,
            "control_pose_source": args.control_pose_source,
            "max_wheel_visual_disagreement_m": args.max_wheel_visual_disagreement_m,
            "wheel_visual_correction_gain": args.wheel_visual_correction_gain,
            "max_wheel_visual_correction_step_m": args.max_wheel_visual_correction_step_m,
            "max_wheel_visual_yaw_correction_deg": args.max_wheel_visual_yaw_correction_deg,
            "wheel_yaw_scale": args.wheel_yaw_scale,
            "wheel_visual_policy": args.wheel_visual_policy,
            "wheel_visual_relocalize_m": args.wheel_visual_relocalize_m,
            "max_wheel_visual_relocalizations": args.max_wheel_visual_relocalizations,
            "relocalization_settle_s": args.relocalization_settle_s,
            "dock_entry_distance_m": args.dock_entry_distance_m,
            "dock_yaw_align_tolerance_deg": args.dock_yaw_align_tolerance_deg,
        },
    }
    if args.dry_run:
        output = {"status": "PASS", "dry_run": True, **summary}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(output, indent=2))
        return 0

    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.duration import Duration
    from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler
    from tf2_ros import Buffer, TransformListener
    from base_keyboard import (
        body_to_wheel_raw,
        encode_sm,
        prepare_wheels_stopped,
        write_wheel_velocities,
    )
    from portutil import BOARDS, PortResolutionError, resolve_port

    rclpy.init()
    node = rclpy.create_node("forestbridge_nav2_supervised_base_execute")
    tf_buffer = Buffer(cache_time=Duration(seconds=5.0))
    listener = TransformListener(tf_buffer, node, spin_thread=False)
    rgbd_odom = LiveRgbdOdom(node, Odometry)
    port_handler = None
    packet = None
    command_writer = None
    status = "FAIL"
    reason = "unknown"
    samples: list[dict[str, Any]] = []
    arrival: dict[str, float] | None = None
    brake_report: dict[str, Any] = {"attempted": False, "active_samples": [], "torque_off_samples": []}
    wheel_tracker: WheelPoseTracker | None = None
    last_visual_correction_count = -1
    relocalization_events: list[dict[str, Any]] = []
    termination_signal: int | None = None
    previous_handlers: dict[int, Any] = {}

    def request_shutdown(signum: int, _frame: Any) -> None:
        nonlocal termination_signal
        termination_signal = signum

    for managed_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[managed_signal] = signal.signal(managed_signal, request_shutdown)
    try:
        tf_deadline = time.monotonic() + 8.0
        first_pose: tuple[float, float, float, float] | None = None
        while time.monotonic() < tf_deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            try:
                candidate = live_pose(tf_buffer, rgbd_odom)
            except Exception:
                continue
            if candidate[3] <= args.max_tf_stale_s:
                first_pose = candidate
                break
        if first_pose is None:
            raise RuntimeError("no fresh RGB-D odometry/map correction before wheel torque")
        start_error = math.hypot(first_pose[0] - points[0][0], first_pose[1] - points[0][1])
        if start_error > args.max_start_error_m:
            raise RuntimeError(
                f"live pose is {start_error:.3f} m from Nav2 path start; refusing to execute an old plan"
            )
        print(json.dumps({**summary, "live_start_map_xy_yaw_deg": list(first_pose[:3]), "path_start_error_m": start_error}, indent=2))
        if os.environ.get("FORESTBRIDGE_DEMO_ARMED") == "1":
            print("AUTO_PIPELINE armed; MOVE is automatically confirmed within the existing path and motion caps.")
        else:
            answer = input(
                "Clear the <=%.2f m route, hold the 12 V cutoff, and type MOVE to enable only wheel IDs 7/8/9: "
                % args.max_planned_path_m
            ).strip()
            if answer != "MOVE":
                reason = "operator_cancelled_before_torque"
                return 2

        # ``input()`` blocks the single-threaded TF listener while the operator
        # performs the physical safety check. Drain that deliberately stale
        # queue and require a new RGB-D odometry transform before any wheel can
        # receive torque or velocity.
        odom_count_before_move = rgbd_odom.count
        post_confirm_deadline = time.monotonic() + 3.0
        while time.monotonic() < post_confirm_deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            try:
                candidate = live_pose(tf_buffer, rgbd_odom)
            except Exception:
                continue
            if rgbd_odom.count >= odom_count_before_move + 2 and candidate[3] <= args.max_tf_stale_s:
                first_pose = candidate
                break
        else:
            raise RuntimeError(
                "no two fresh RGB-D odometry messages after MOVE confirmation; wheel torque remained off"
            )
        start_error = math.hypot(first_pose[0] - points[0][0], first_pose[1] - points[0][1])
        if start_error > args.max_start_error_m:
            raise RuntimeError(
                f"live pose changed to {start_error:.3f} m from Nav2 path start while awaiting MOVE; refusing plan"
            )

        override = args.port or os.environ.get("XLEROBOT_PORT")
        try:
            port = resolve_port(BOARDS["white"], override=override)
        except PortResolutionError as exc:
            raise RuntimeError(str(exc)) from exc
        port_handler = PortHandler(port)
        if not port_handler.openPort():
            raise RuntimeError(f"cannot open white base port {port}")
        if not port_handler.setBaudRate(1_000_000):
            port_handler.closePort()
            port_handler = None
            raise RuntimeError("cannot set white base serial baud rate")
        packet = PacketHandler(0)
        missing = []
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(port_handler, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                missing.append(motor_id)
        if missing:
            raise RuntimeError(f"base motor IDs did not respond before torque: {missing}")
        command_writer = GroupSyncWrite(port_handler, packet, GOAL_VEL, 2)
        # Set the shutdown-capable writer before the first torque-enable write.
        # A partial preparation failure must still enter verified shutdown.
        prepare_wheels_stopped(packet, port_handler, COMM_SUCCESS, GroupSyncWrite)
        if args.control_pose_source == "wheel":
            # Seed only after serial ownership and mode/torque preparation have
            # succeeded. The global anchor remains the current map-localized
            # pose; wheel feedback supplies the high-rate local correction.
            wheel_tracker = WheelPoseTracker(first_pose[:3], yaw_scale=args.wheel_yaw_scale)
            wheel_tracker.update(
                read_wheel_velocity_raw(packet, port_handler, COMM_SUCCESS),
                time.monotonic(),
            )

        start_time = time.monotonic()
        previous_pose = first_pose
        tracked_travel = 0.0
        # A Nav2 path is ordered.  Do not use the relatively generous arrival
        # tolerance to skip its opening points before the base has made any
        # verified translation: that shortcut previously selected a distant
        # waypoint and created a large, unintended initial turn.
        waypoint_index = 0
        best_goal_distance = math.hypot(first_pose[0] - points[-1][0], first_pose[1] - points[-1][1])
        best_path_heading_error = 180.0
        best_goal_yaw_error = abs(wrap_degrees(points[-1][2] - first_pose[2]))
        last_progress_time = start_time
        final_goal = points[-1]
        rotation_anchor_xy: tuple[float, float] | None = None
        feedback_mode = "stopped"
        dock_phase = "disabled" if args.dock_entry_distance_m == 0.0 else "approach"
        period = 1.0 / LOOP_HZ
        while True:
            loop_started = time.monotonic()
            if termination_signal is not None:
                raise RuntimeError(f"received shutdown signal {termination_signal}")
            rclpy.spin_once(node, timeout_sec=0.05)
            visual_x, visual_y, visual_yaw, age_s = live_pose(tf_buffer, rgbd_odom)
            if age_s > args.max_tf_stale_s:
                raise RuntimeError(f"RGB-D odometry receive age is {age_s:.3f} s")
            wheel_raw: dict[int, int] | None = None
            wheel_visual_disagreement_m: float | None = None
            fused_visual_disagreement_m: float | None = None
            visual_correction_m: float | None = None
            visual_yaw_correction_deg: float | None = None
            if args.control_pose_source == "wheel":
                if wheel_tracker is None:
                    raise RuntimeError("wheel control pose was not initialized")
                wheel_raw = read_wheel_velocity_raw(packet, port_handler, COMM_SUCCESS)
                current_x, current_y, current_yaw = wheel_tracker.update(
                    wheel_raw, time.monotonic()
                )
                wheel_visual_disagreement_m = math.hypot(current_x - visual_x, current_y - visual_y)
                # Pure turns are intentionally wheel-only: moving camera
                # features can report false translation while the chassis is
                # rotating in place. During actual translation, incorporate
                # each *new* RGB-D sample with a bounded complementary update.
                # A moderate disagreement gets one bounded stop-and-reanchor
                # from the map-frame visual pose. A larger innovation, or a
                # second disagreement beyond the supervised cap, still fails
                # closed before it can be blended into the control pose.
                if feedback_mode == "translate" and args.wheel_visual_policy == "bounded":
                    if wheel_visual_disagreement_m > args.max_wheel_visual_disagreement_m:
                        raise RuntimeError(
                            "wheel/RGB-D translation disagreement "
                            f"{wheel_visual_disagreement_m:.3f} m exceeds "
                            f"{args.max_wheel_visual_disagreement_m:.3f} m"
                        )
                    if wheel_visual_disagreement_m > args.wheel_visual_relocalize_m:
                        if len(relocalization_events) >= args.max_wheel_visual_relocalizations:
                            raise RuntimeError(
                                "wheel/RGB-D disagreement requires another map re-localization "
                                f"({wheel_visual_disagreement_m:.3f} m), but the supervised cap is "
                                f"{args.max_wheel_visual_relocalizations}"
                            )
                        # The chassis must be still before using the map-frame
                        # pose as a new anchor. Keep torque enabled but command
                        # zero throughout the short observation window; any
                        # observation failure exits through verified shutdown.
                        write_wheel_velocities(
                            command_writer,
                            port_handler,
                            [0, 0, 0],
                            COMM_SUCCESS,
                        )
                        reanchored_pose, reanchor_stats = settle_map_relocalization(
                            node,
                            tf_buffer,
                            rgbd_odom,
                            settle_s=args.relocalization_settle_s,
                            max_spread_m=args.relocalization_max_spread_m,
                            max_yaw_spread_deg=args.relocalization_max_yaw_spread_deg,
                            max_tf_stale_s=args.max_tf_stale_s,
                        )
                        wheel_tracker = WheelPoseTracker(
                            reanchored_pose[:3], yaw_scale=args.wheel_yaw_scale
                        )
                        wheel_tracker.update(
                            read_wheel_velocity_raw(packet, port_handler, COMM_SUCCESS),
                            time.monotonic(),
                        )
                        last_visual_correction_count = rgbd_odom.count
                        current_x, current_y, current_yaw = wheel_tracker.x_m, wheel_tracker.y_m, wheel_tracker.yaw_deg
                        previous_pose = (current_x, current_y, current_yaw, reanchored_pose[3])
                        rotation_anchor_xy = None
                        feedback_mode = "stopped"
                        last_progress_time = time.monotonic()
                        event = {
                            "event": "map_relocalized_after_wheel_visual_disagreement",
                            "elapsed_s": round(loop_started - start_time, 3),
                            "raw_wheel_visual_disagreement_m": round(wheel_visual_disagreement_m, 4),
                            "map_x": round(current_x, 4),
                            "map_y": round(current_y, 4),
                            "map_yaw_deg": round(current_yaw, 2),
                            **{key: round(value, 4) for key, value in reanchor_stats.items()},
                        }
                        relocalization_events.append(event)
                        samples.append(event)
                        continue
                    if rgbd_odom.count != last_visual_correction_count:
                        (
                            wheel_visual_disagreement_m,
                            visual_correction_m,
                            visual_yaw_correction_deg,
                        ) = wheel_tracker.correct_toward_visual(
                            (visual_x, visual_y, visual_yaw),
                            gain=args.wheel_visual_correction_gain,
                            max_position_step_m=args.max_wheel_visual_correction_step_m,
                            max_yaw_step_deg=args.max_wheel_visual_yaw_correction_deg,
                        )
                        last_visual_correction_count = rgbd_odom.count
                        current_x, current_y, current_yaw = (
                            wheel_tracker.x_m,
                            wheel_tracker.y_m,
                            wheel_tracker.yaw_deg,
                        )
                    fused_visual_disagreement_m = math.hypot(
                        current_x - visual_x,
                        current_y - visual_y,
                    )
            else:
                current_x, current_y, current_yaw = visual_x, visual_y, visual_yaw
            step_distance = math.hypot(current_x - previous_pose[0], current_y - previous_pose[1])
            tracked_travel += step_distance
            previous_pose = (current_x, current_y, current_yaw, age_s)
            if tracked_travel > args.max_tracked_travel_m:
                raise RuntimeError(f"tracked base travel {tracked_travel:.3f} m exceeds cap")
            elapsed = loop_started - start_time
            if elapsed > args.max_runtime_s:
                raise RuntimeError(f"execution exceeded {args.max_runtime_s:.1f} s cap")

            goal_distance = math.hypot(final_goal[0] - current_x, final_goal[1] - current_y)
            yaw_error_to_goal = wrap_degrees(final_goal[2] - current_yaw)
            if feedback_mode == "rotate":
                if rotation_anchor_xy is None:
                    raise RuntimeError("rotate-only feedback is missing its pose anchor")
                validate_rotate_only_feedback(
                    rotation_anchor_xy,
                    current_x,
                    current_y,
                    args.max_rotate_translation_m,
                )
            waypoint_index = advance_waypoint_index(
                points,
                current_x,
                current_y,
                waypoint_index,
                args.position_tolerance_m,
                allow_translation_progress=feedback_mode == "translate",
            )
            steering_index = lookahead_waypoint_index(
                points,
                current_x,
                current_y,
                waypoint_index,
                args.path_lookahead_m,
            )
            target_x, target_y, _ = points[steering_index]
            target_distance = math.hypot(target_x - current_x, target_y - current_y)
            desired_heading = math.degrees(math.atan2(target_y - current_y, target_x - current_x))
            heading_error = wrap_degrees(desired_heading - current_yaw)
            rotate_only = abs(heading_error) > 12.0
            if dock_phase == "approach" and goal_distance <= args.dock_entry_distance_m:
                # At the entry radius there is still clearance to align the
                # chassis. Once aligned, the table-side phase never rotates.
                dock_phase = "align"
            progress_heading_error = yaw_error_to_goal if dock_phase == "align" else heading_error
            if goal_distance > args.position_tolerance_m:
                made_progress, best_goal_distance, best_path_heading_error = path_alignment_progress(
                    goal_distance,
                    best_goal_distance,
                    progress_heading_error,
                    best_path_heading_error,
                    feedback_mode=feedback_mode,
                )
                if made_progress:
                    last_progress_time = loop_started
                elif loop_started - last_progress_time > args.progress_timeout_s:
                    raise RuntimeError("no meaningful goal-distance progress within timeout")
            elif abs(yaw_error_to_goal) + 2.0 < best_goal_yaw_error:
                # Once translation is complete, the correct success signal is
                # rotational progress. The former distance-only watchdog
                # aborted an otherwise correct final heading alignment.
                best_goal_yaw_error = abs(yaw_error_to_goal)
                last_progress_time = loop_started
            elif loop_started - last_progress_time > args.progress_timeout_s:
                raise RuntimeError("no meaningful final-yaw progress within timeout")

            body_vx = 0.0
            body_vy = 0.0
            if dock_phase == "align" and abs(yaw_error_to_goal) <= args.dock_yaw_align_tolerance_deg:
                dock_phase = "translate"
                rotation_anchor_xy = None

            if dock_phase == "translate":
                if abs(yaw_error_to_goal) > args.dock_yaw_align_tolerance_deg:
                    # A table dock requires the front edge to stay parallel
                    # to the table. Pause translation, recover that heading,
                    # then resume the same holonomic approach. This is an
                    # explicit dock-only state transition, not the ordinary
                    # path follower's unconstrained turn toward a waypoint.
                    dock_phase = "align"
                if dock_phase == "translate" and goal_distance <= args.position_tolerance_m:
                    write_wheel_velocities(command_writer, port_handler, [0, 0, 0], COMM_SUCCESS)
                    arrival = {
                        "elapsed_s": round(elapsed, 3),
                        "x": round(current_x, 4),
                        "y": round(current_y, 4),
                        "yaw_deg": round(current_yaw, 2),
                        "goal_distance_m": round(goal_distance, 4),
                        "goal_yaw_error_deg": round(yaw_error_to_goal, 2),
                        "dock_phase": dock_phase,
                    }
                    samples.append({"event": "goal_reached", **arrival})
                    status = "PASS"
                    reason = "dock_goal_position_and_yaw_reached"
                    break
                if dock_phase == "translate":
                    speed = min(args.max_linear_mps, max(0.015, 0.45 * goal_distance))
                    body_vx, body_vy = map_delta_to_body_velocity(
                        final_goal[0] - current_x, final_goal[1] - current_y, current_yaw, speed
                    )
                    linear = math.hypot(body_vx, body_vy)
                    angular = 0.0
                    yaw_error = yaw_error_to_goal
            if dock_phase == "align":
                linear = 0.0
                angular = max(
                    -args.max_angular_deg_s,
                    min(args.max_angular_deg_s, 0.6 * yaw_error_to_goal),
                )
                yaw_error = yaw_error_to_goal
            elif dock_phase != "translate" and goal_distance <= args.position_tolerance_m:
                yaw_error = yaw_error_to_goal
                if abs(yaw_error) <= args.yaw_tolerance_deg:
                    write_wheel_velocities(command_writer, port_handler, [0, 0, 0], COMM_SUCCESS)
                    # This pose is sampled *after* the goal gate. The prior
                    # report only retained the preceding control iteration,
                    # which made a successful arrival look short of its goal.
                    arrival = {
                        "elapsed_s": round(elapsed, 3),
                        "x": round(current_x, 4),
                        "y": round(current_y, 4),
                        "yaw_deg": round(current_yaw, 2),
                        "goal_distance_m": round(goal_distance, 4),
                        "goal_yaw_error_deg": round(yaw_error, 2),
                    }
                    samples.append({"event": "goal_reached", **arrival})
                    status = "PASS"
                    reason = "goal_position_and_yaw_reached"
                    break
                linear = 0.0
                angular = max(-args.max_angular_deg_s, min(args.max_angular_deg_s, 0.6 * yaw_error))
            elif dock_phase != "translate":
                angular = max(-args.max_angular_deg_s, min(args.max_angular_deg_s, 0.6 * heading_error))
                # For the first real run, rotate before driving rather than
                # combining translation and yaw. This keeps observed motion
                # simple and makes Ctrl-C/cutoff behaviour unambiguous.
                linear = 0.0 if rotate_only else min(
                    args.max_linear_mps, max(0.015, 0.45 * target_distance)
                )
                yaw_error = heading_error

            if dock_phase != "translate":
                body_vx = linear
                body_vy = 0.0
            raw = body_to_wheel_raw(body_vx, body_vy, angular)
            write_wheel_velocities(
                command_writer,
                port_handler,
                [encode_sm(velocity) for velocity in raw],
                COMM_SUCCESS,
            )
            next_feedback_mode = "translate" if linear > 0.0 else "rotate" if angular != 0.0 else "stopped"
            if next_feedback_mode == "rotate" and feedback_mode != "rotate":
                rotation_anchor_xy = (current_x, current_y)
                # A later path segment can require a larger turn than an
                # earlier one. Give each distinct rotation its own progress
                # baseline and timeout window.
                best_path_heading_error = rotation_progress_baseline(
                    feedback_mode,
                    next_feedback_mode,
                    progress_heading_error,
                    best_path_heading_error,
                )
                last_progress_time = loop_started
            elif next_feedback_mode != "rotate":
                rotation_anchor_xy = None
            feedback_mode = next_feedback_mode
            samples.append(
                {
                    "elapsed_s": round(elapsed, 3),
                    "x": round(current_x, 4),
                    "y": round(current_y, 4),
                    "yaw_deg": round(current_yaw, 2),
                    "goal_distance_m": round(goal_distance, 4),
                    "path_index": float(waypoint_index),
                    "steering_index": float(steering_index),
                    "linear_mps": round(linear, 4),
                    "body_vx_mps": round(body_vx, 4),
                    "body_vy_mps": round(body_vy, 4),
                    "angular_deg_s": round(angular, 3),
                    "dock_phase": dock_phase,
                    "control_pose_source": args.control_pose_source,
                    "visual_x": round(visual_x, 4),
                    "visual_y": round(visual_y, 4),
                    "visual_yaw_deg": round(visual_yaw, 2),
                    "wheel_velocity_raw": wheel_raw,
                    "wheel_visual_disagreement_m": (
                        round(wheel_visual_disagreement_m, 4)
                        if wheel_visual_disagreement_m is not None
                        else None
                    ),
                    "fused_visual_disagreement_m": (
                        round(fused_visual_disagreement_m, 4)
                        if fused_visual_disagreement_m is not None
                        else None
                    ),
                    "visual_correction_m": (
                        round(visual_correction_m, 4)
                        if visual_correction_m is not None
                        else None
                    ),
                    "visual_yaw_correction_deg": (
                        round(visual_yaw_correction_deg, 3)
                        if visual_yaw_correction_deg is not None
                        else None
                    ),
                }
            )
            time.sleep(max(0.0, period - (time.monotonic() - loop_started)))
    except KeyboardInterrupt:
        reason = "operator_interrupt"
    except Exception as exc:
        reason = str(exc)
    finally:
        shutdown_errors: list[str] = []
        if packet is not None and port_handler is not None:
            # A single zero command immediately followed by torque release is
            # only a bus transaction, not evidence that the chassis stopped.
            # Reuse the active-braking pattern independently verified in the
            # one-second base diagnostic before releasing any wheel torque.
            brake_report["attempted"] = True
            if command_writer is not None:
                from base_stop_diagnostic import read_wheels, stop_readback_confirmed
                brake_report, verified_errors = brake_and_verify_release(
                    packet,
                    port_handler,
                    command_writer,
                    COMM_SUCCESS,
                    args.brake_s,
                    write_zero=write_wheel_velocities,
                    read_wheels=read_wheels,
                    stop_readback_confirmed=stop_readback_confirmed,
                )
                shutdown_errors.extend(verified_errors)
                try:
                    port_handler.closePort()
                except Exception as exc:
                    shutdown_errors.append(f"serial close failed: {exc}")
            else:
                shutdown_errors = zero_and_release(packet, port_handler, COMM_SUCCESS)
                brake_report["reason"] = "wheel torque was never prepared; used best-effort release"
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()
        for managed_signal, previous_handler in previous_handlers.items():
            signal.signal(managed_signal, previous_handler)
        output = {
            **summary,
            "status": status,
            "reason": reason,
            "samples": samples,
            "arrival": arrival,
            "map_relocalizations": relocalization_events,
            "shutdown_brake": brake_report,
            "shutdown_errors": shutdown_errors,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**output, "samples": f"{len(samples)} samples written to {args.output}"}, indent=2))
        if shutdown_errors:
            print("WARNING: base shutdown was incomplete; use the 12 V cutoff immediately.", file=sys.stderr)
            status = "FAIL"
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
