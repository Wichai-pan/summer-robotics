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
LOOP_HZ = 5.0
STOP_BUS_SETTLE_S = 0.2
STOP_READBACK_PERIOD_S = 0.5


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


def validate_rotate_only_feedback(
    anchor_xy: tuple[float, float],
    current_x: float,
    current_y: float,
    maximum_translation_m: float,
) -> float:
    """Reject camera-only translation produced by an in-place turn."""
    translation_m = math.hypot(current_x - anchor_xy[0], current_y - anchor_xy[1])
    if translation_m > maximum_translation_m:
        raise RuntimeError(
            "rotate-only RGB-D pose reported "
            f"{translation_m:.3f} m translation; camera-only base feedback is inconsistent"
        )
    return translation_m


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
        args.max_rotate_translation_m,
        args.brake_s,
    )
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("all execution limits must be finite and > 0")
    if args.max_linear_mps > 0.08 or args.max_angular_deg_s > 20.0:
        raise ValueError("first-motion speed caps are fixed at <=0.08 m/s and <=20 deg/s")
    if args.brake_s > 1.0:
        raise ValueError("first-motion active braking is capped at <=1.0 s")


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
        communication = packet.write1ByteTxOnly(port_handler, motor_id, address, value)
        if communication != communication_success:
            last_error = f"write communication={communication}"
            time.sleep(0.1)
            continue
        time.sleep(0.05)
        observed, communication, packet_error = packet.read1ByteTxRx(port_handler, motor_id, address)
        if communication == communication_success and packet_error == 0 and int(observed) == value:
            return None
        last_error = (
            f"read value={observed}, communication={communication}, packet_error={packet_error}"
        )
        time.sleep(0.1)
    return f"{label} ID {motor_id} failed after {retries} attempts: {last_error}"


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
            raise RuntimeError("cannot set white base serial baud rate")
        packet = PacketHandler(0)
        missing = []
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(port_handler, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                missing.append(motor_id)
        if missing:
            raise RuntimeError(f"base motor IDs did not respond before torque: {missing}")
        prepare_wheels_stopped(packet, port_handler, COMM_SUCCESS, GroupSyncWrite)
        command_writer = GroupSyncWrite(port_handler, packet, GOAL_VEL, 2)

        start_time = time.monotonic()
        previous_pose = first_pose
        tracked_travel = 0.0
        waypoint_index = advance_waypoint_index(
            points,
            first_pose[0],
            first_pose[1],
            0,
            args.position_tolerance_m,
            allow_translation_progress=True,
        )
        best_goal_distance = math.hypot(first_pose[0] - points[-1][0], first_pose[1] - points[-1][1])
        best_path_heading_error = 180.0
        best_goal_yaw_error = abs(wrap_degrees(points[-1][2] - first_pose[2]))
        last_progress_time = start_time
        final_goal = points[-1]
        rotation_anchor_xy: tuple[float, float] | None = None
        feedback_mode = "stopped"
        period = 1.0 / LOOP_HZ
        while True:
            loop_started = time.monotonic()
            if termination_signal is not None:
                raise RuntimeError(f"received shutdown signal {termination_signal}")
            rclpy.spin_once(node, timeout_sec=0.05)
            current_x, current_y, current_yaw, age_s = live_pose(tf_buffer, rgbd_odom)
            if age_s > args.max_tf_stale_s:
                raise RuntimeError(f"RGB-D odometry receive age is {age_s:.3f} s")
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
            target_x, target_y, _ = points[waypoint_index]
            target_distance = math.hypot(target_x - current_x, target_y - current_y)
            desired_heading = math.degrees(math.atan2(target_y - current_y, target_x - current_x))
            heading_error = wrap_degrees(desired_heading - current_yaw)
            rotate_only = abs(heading_error) > 12.0
            if goal_distance > args.position_tolerance_m:
                made_progress, best_goal_distance, best_path_heading_error = path_alignment_progress(
                    goal_distance,
                    best_goal_distance,
                    heading_error,
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

            if goal_distance <= args.position_tolerance_m:
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
            else:
                angular = max(-args.max_angular_deg_s, min(args.max_angular_deg_s, 0.6 * heading_error))
                # For the first real run, rotate before driving rather than
                # combining translation and yaw. This keeps observed motion
                # simple and makes Ctrl-C/cutoff behaviour unambiguous.
                linear = 0.0 if rotate_only else min(
                    args.max_linear_mps, max(0.015, 0.45 * target_distance)
                )
                yaw_error = heading_error

            raw = body_to_wheel_raw(linear, 0.0, angular)
            write_wheel_velocities(
                command_writer,
                port_handler,
                [encode_sm(velocity) for velocity in raw],
                COMM_SUCCESS,
            )
            next_feedback_mode = "translate" if linear > 0.0 else "rotate" if angular != 0.0 else "stopped"
            if next_feedback_mode == "rotate" and feedback_mode != "rotate":
                rotation_anchor_xy = (current_x, current_y)
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
                    "target_index": float(waypoint_index),
                    "linear_mps": round(linear, 4),
                    "angular_deg_s": round(angular, 3),
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

                brake_deadline = time.monotonic() + args.brake_s
                while time.monotonic() < brake_deadline:
                    try:
                        write_wheel_velocities(command_writer, port_handler, [0, 0, 0], COMM_SUCCESS)
                    except Exception as exc:
                        shutdown_errors.append(f"active zero velocity failed: {exc}")
                    brake_report["active_samples"].append(
                        {"phase": "brake_zero_command", "time_monotonic_s": time.monotonic()}
                    )
                    time.sleep(0.1)

                # Let any pending status bytes clear before per-wheel
                # torque-off writes and their independent verification reads.
                time.sleep(STOP_BUS_SETTLE_S)

                # Keep the port open for a final register read-back after
                # torque release. The evidence is recorded in the run JSON.
                for motor_id in WHEEL_IDS:
                    # Velocity was repeatedly zeroed in the broadcast above.
                    # Each Tx-only torque write is followed by a delayed,
                    # independent register read in write_and_verify_byte().
                    error = write_and_verify_byte(
                        packet, port_handler, motor_id, TORQUE, 0, COMM_SUCCESS, "disable torque"
                    )
                    if error is not None:
                        shutdown_errors.append(error)
                time.sleep(STOP_BUS_SETTLE_S)
                for _ in range(3):
                    brake_report["torque_off_samples"].append(
                        {"phase": "torque_off_observe", **read_wheels(packet, port_handler)}
                    )
                    time.sleep(STOP_READBACK_PERIOD_S)
                brake_samples = [*brake_report["active_samples"], *brake_report["torque_off_samples"]]
                brake_report["stop_readback_confirmed"] = stop_readback_confirmed(brake_samples)
                if not brake_report["stop_readback_confirmed"]:
                    shutdown_errors.append("wheel stop read-back was not confirmed")
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
