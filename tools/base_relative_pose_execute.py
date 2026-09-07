#!/usr/bin/env python3
"""Execute one short wheel-feedback relative pose move without camera localization."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any


def relative_pose_command(
    x: float,
    y: float,
    yaw_deg: float,
    target_x: float,
    target_y: float,
    target_yaw_deg: float,
    max_linear_mps: float,
    max_angular_deg_s: float,
    position_tolerance_m: float,
) -> tuple[float, float, float, float, float]:
    try:
        from nav2_supervised_base_execute import map_delta_to_body_velocity, wrap_degrees
    except ModuleNotFoundError:
        from tools.nav2_supervised_base_execute import map_delta_to_body_velocity, wrap_degrees

    dx, dy = target_x - x, target_y - y
    distance = math.hypot(dx, dy)
    yaw_error = wrap_degrees(target_yaw_deg - yaw_deg)
    angular = max(-max_angular_deg_s, min(max_angular_deg_s, 0.6 * yaw_error))
    if distance <= position_tolerance_m:
        return 0.0, 0.0, angular, distance, yaw_error
    speed = min(max_linear_mps, max(0.012, 0.5 * distance))
    body_vx, body_vy = map_delta_to_body_velocity(dx, dy, yaw_deg, speed)
    return body_vx, body_vy, angular, distance, yaw_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x-m", type=float, required=True)
    parser.add_argument("--y-m", type=float, required=True)
    parser.add_argument("--yaw-deg", type=float, required=True)
    parser.add_argument("--max-linear-mps", type=float, default=0.04)
    parser.add_argument("--max-angular-deg-s", type=float, default=8.0)
    parser.add_argument("--max-runtime-s", type=float, default=20.0)
    parser.add_argument("--position-tolerance-m", type=float, default=0.015)
    parser.add_argument("--yaw-tolerance-deg", type=float, default=1.0)
    parser.add_argument("--max-travel-m", type=float, default=0.30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    values = (
        args.x_m, args.y_m, args.yaw_deg, args.max_linear_mps,
        args.max_angular_deg_s, args.max_runtime_s, args.position_tolerance_m,
        args.yaw_tolerance_deg, args.max_travel_m,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("all relative-motion values must be finite")
    distance = math.hypot(args.x_m, args.y_m)
    if not 0.0 < distance <= 1.00:
        raise ValueError("relative XY distance must be in (0, 1.00] m")
    if abs(args.yaw_deg) > 15.0:
        raise ValueError("relative yaw is limited to 15 degrees")
    if not 0.0 < args.max_linear_mps <= 0.04:
        raise ValueError("maximum linear speed must be in (0, 0.04] m/s")
    if not 0.0 < args.max_angular_deg_s <= 12.0:
        raise ValueError("maximum angular speed must be in (0, 12] deg/s")
    if not 0.0 < args.max_runtime_s <= 45.0:
        raise ValueError("runtime must be in (0, 45] s")
    if not distance < args.max_travel_m <= 1.20:
        raise ValueError("travel cap must exceed target distance and be <=1.20 m")


def main() -> int:
    args = parse_args()
    validate_args(args)
    target = (args.x_m, args.y_m, args.yaw_deg)
    if args.dry_run:
        command = relative_pose_command(
            0.0, 0.0, 0.0, *target, args.max_linear_mps,
            args.max_angular_deg_s, args.position_tolerance_m,
        )
        print(json.dumps({"status": "PASS", "dry_run": True, "target": target, "first_command": command}, indent=2))
        return 0

    from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler
    from base_keyboard import GOAL_VEL, WHEEL_IDS, body_to_wheel_raw, encode_sm, prepare_wheels_stopped, write_wheel_velocities
    from base_stop_diagnostic import read_wheels, stop_readback_confirmed
    from nav2_supervised_base_execute import WheelPoseTracker, brake_and_verify_release, read_wheel_velocity_raw
    from portutil import BOARDS, PortResolutionError, resolve_port

    if os.environ.get("FORESTBRIDGE_DEMO_ARMED") != "1":
        answer = input(
            f"Relative wheel-only target x={args.x_m:+.3f} y={args.y_m:+.3f} m, "
            f"yaw={args.yaw_deg:+.2f} deg. Type MOVE: "
        ).strip()
        if answer != "MOVE":
            print("Cancelled before opening the white controller.")
            return 2

    try:
        port_name = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    port = PortHandler(port_name)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        raise RuntimeError(f"cannot open white board {port_name}")
    packet = PacketHandler(0)
    writer = GroupSyncWrite(port, packet, GOAL_VEL, 2)
    tracker = WheelPoseTracker((0.0, 0.0, 0.0), yaw_scale=0.75)
    samples: list[dict[str, Any]] = []
    shutdown: dict[str, Any] = {"attempted": False}
    shutdown_errors: list[str] = []
    prepared = False
    success = False
    reason = "unknown"
    try:
        missing = []
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(port, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                missing.append(motor_id)
        if missing:
            raise RuntimeError(f"base motor IDs did not respond: {missing}")
        prepared = True
        prepare_wheels_stopped(packet, port, COMM_SUCCESS, GroupSyncWrite)
        tracker.update(read_wheel_velocity_raw(packet, port, COMM_SUCCESS), time.monotonic())
        started = time.monotonic()
        previous_xy = (0.0, 0.0)
        tracked_travel = 0.0
        best_distance = math.hypot(args.x_m, args.y_m)
        best_yaw_error = abs(args.yaw_deg)
        last_progress = started
        while True:
            loop_started = time.monotonic()
            x, y, yaw = tracker.update(
                read_wheel_velocity_raw(packet, port, COMM_SUCCESS), loop_started
            )
            tracked_travel += math.hypot(x - previous_xy[0], y - previous_xy[1])
            previous_xy = (x, y)
            if tracked_travel > args.max_travel_m:
                raise RuntimeError(f"tracked travel {tracked_travel:.3f} m exceeds cap")
            body_vx, body_vy, angular, distance, yaw_error = relative_pose_command(
                x, y, yaw, *target, args.max_linear_mps,
                args.max_angular_deg_s, args.position_tolerance_m,
            )
            elapsed = loop_started - started
            if distance <= args.position_tolerance_m and abs(yaw_error) <= args.yaw_tolerance_deg:
                success = True
                reason = "relative_pose_reached"
                write_wheel_velocities(writer, port, [0, 0, 0], COMM_SUCCESS)
                samples.append({"elapsed_s": elapsed, "x": x, "y": y, "yaw_deg": yaw, "distance_error_m": distance, "yaw_error_deg": yaw_error})
                break
            if elapsed > args.max_runtime_s:
                raise RuntimeError("relative motion runtime exceeded")
            if distance + 0.008 < best_distance or abs(yaw_error) + 0.8 < best_yaw_error:
                best_distance = min(best_distance, distance)
                best_yaw_error = min(best_yaw_error, abs(yaw_error))
                last_progress = loop_started
            elif loop_started - last_progress > 5.0:
                raise RuntimeError("no relative pose progress for 5 seconds")
            raw = body_to_wheel_raw(body_vx, body_vy, angular)
            write_wheel_velocities(writer, port, [encode_sm(value) for value in raw], COMM_SUCCESS)
            samples.append({"elapsed_s": elapsed, "x": x, "y": y, "yaw_deg": yaw, "distance_error_m": distance, "yaw_error_deg": yaw_error, "body_vx_mps": body_vx, "body_vy_mps": body_vy, "angular_deg_s": angular})
            time.sleep(max(0.0, 0.2 - (time.monotonic() - loop_started)))
    except Exception as exc:
        reason = str(exc)
    finally:
        if prepared:
            shutdown, shutdown_errors = brake_and_verify_release(
                packet, port, writer, COMM_SUCCESS, 0.8,
                write_zero=write_wheel_velocities, read_wheels=read_wheels,
                stop_readback_confirmed=stop_readback_confirmed,
            )
        port.closePort()
    status = "PASS" if success and not shutdown_errors else "FAIL"
    report = {"status": status, "reason": reason, "target_relative_pose": target, "samples": samples, "shutdown_brake": shutdown, "shutdown_errors": shutdown_errors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "samples": f"{len(samples)} samples written to {args.output}"}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
