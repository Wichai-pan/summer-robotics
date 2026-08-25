#!/usr/bin/env python3
"""Run one bounded, open-space base rotation and record the wheel evidence.

This is a calibration diagnostic, not navigation: it never opens Gemini,
loads a map, or commands white-arm IDs 1--6.  It uses only wheel IDs 7/8/9,
integrates their *present* velocities, and fails closed if a rotate-only
command accumulates more than the allowed XY drift.  Every exit uses the
shared repeated-zero active brake and verified torque-release sequence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any

WHEEL_IDS = (7, 8, 9)
GOAL_VELOCITY = 46


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direction", choices=("left", "right"), default="left")
    parser.add_argument("--target-deg", type=float, default=30.0)
    parser.add_argument("--angular-deg-s", type=float, default=12.0)
    parser.add_argument("--max-translation-m", type=float, default=0.05)
    parser.add_argument("--brake-s", type=float, default=0.8)
    parser.add_argument("--output", type=Path, default=Path("/data/slam/base-turn-diagnostic.json"))
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    values = (args.target_deg, args.angular_deg_s, args.max_translation_m, args.brake_s)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("all numeric arguments must be finite")
    if not 5.0 <= args.target_deg <= 90.0:
        raise ValueError("--target-deg must be in [5, 90]")
    if not 1.0 <= args.angular_deg_s <= 12.0:
        raise ValueError("--angular-deg-s must be in [1, 12]")
    if not 0.01 <= args.max_translation_m <= 0.05:
        raise ValueError("--max-translation-m must be in [0.01, 0.05]")
    if not 0.5 <= args.brake_s <= 1.0:
        raise ValueError("--brake-s must be in [0.5, 1.0]")


def direction_sign(direction: str) -> float:
    """Return the established keyboard-theta sign (Q left, E right)."""
    if direction == "left":
        return 1.0
    if direction == "right":
        return -1.0
    raise ValueError(f"unknown direction {direction!r}")


def main() -> int:
    args = parse_args()
    validate_args(args)

    from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler

    from base_keyboard import body_to_wheel_raw, encode_sm, prepare_wheels_stopped, write_wheel_velocities
    from base_stop_diagnostic import read_wheels, stop_readback_confirmed
    from nav2_supervised_base_execute import WheelPoseTracker, brake_and_verify_release, validate_rotate_only_feedback
    from portutil import BOARDS, PortResolutionError, resolve_port

    try:
        port_name = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    port = PortHandler(port_name)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        raise SystemExit(f"cannot open white board {port_name}")
    packet = PacketHandler(0)
    writer = GroupSyncWrite(port, packet, GOAL_VELOCITY, 2)
    samples: list[dict[str, Any]] = []
    shutdown_errors: list[str] = []
    brake_report: dict[str, Any] = {"attempted": False, "active_samples": [], "torque_off_samples": []}
    prepared = False
    shutdown_attempted = False
    reason = "not_started"
    target_signed_deg = direction_sign(args.direction) * args.target_deg
    commanded_angular_deg_s = direction_sign(args.direction) * args.angular_deg_s
    raw = body_to_wheel_raw(0.0, 0.0, commanded_angular_deg_s)

    try:
        missing = []
        for motor_id in WHEEL_IDS:
            _model, communication, packet_error = packet.ping(port, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                missing.append(motor_id)
        if missing:
            raise RuntimeError(f"base motor IDs did not respond: {missing}; no torque enabled")

        print(
            "Open-space rotation only: "
            f"{args.direction} {args.target_deg:.0f} deg at <= {args.angular_deg_s:.1f} deg/s "
            f"-> {dict(zip(WHEEL_IDS, raw))} raw"
        )
        answer = input(
            "Mark the start arrow and target angle on the floor; clear a 0.5 m radius, "
            "hold the 12 V cutoff, then type TURN: "
        ).strip()
        if answer != "TURN":
            reason = "operator_cancelled_before_writes"
            return 2

        prepared = True
        prepare_wheels_stopped(packet, port, COMM_SUCCESS, GroupSyncWrite)
        tracker = WheelPoseTracker((0.0, 0.0, 0.0))
        anchor_xy = (0.0, 0.0)
        deadline = time.monotonic() + 1.5 * args.target_deg / args.angular_deg_s + 1.0
        while time.monotonic() < deadline:
            write_wheel_velocities(writer, port, [encode_sm(value) for value in raw], COMM_SUCCESS)
            now_s = time.monotonic()
            record = read_wheels(packet, port)
            raw_by_id: dict[int, int] = {}
            for motor_id in WHEEL_IDS:
                value = record["wheels"][str(motor_id)].get("present_velocity_signed_raw")
                if not isinstance(value, int):
                    raise RuntimeError(f"ID {motor_id} has no usable present velocity: {value!r}")
                raw_by_id[motor_id] = value
            x_m, y_m, yaw_deg = tracker.update(raw_by_id, now_s)
            drift_m = validate_rotate_only_feedback(anchor_xy, x_m, y_m, args.max_translation_m)
            samples.append(
                {
                    "phase": "turn",
                    "commanded_angular_deg_s": commanded_angular_deg_s,
                    "wheel_pose_xy_yaw_deg": [x_m, y_m, yaw_deg],
                    "rotate_translation_m": drift_m,
                    **record,
                }
            )
            if (target_signed_deg > 0 and yaw_deg >= target_signed_deg) or (
                target_signed_deg < 0 and yaw_deg <= target_signed_deg
            ):
                reason = "wheel_feedback_target_reached"
                break
            time.sleep(0.1)
        else:
            reason = "target_not_reached_before_bounded_deadline"

        brake_report, verified_errors = brake_and_verify_release(
            packet,
            port,
            writer,
            COMM_SUCCESS,
            args.brake_s,
            write_zero=write_wheel_velocities,
            read_wheels=read_wheels,
            stop_readback_confirmed=stop_readback_confirmed,
        )
        shutdown_attempted = True
        samples.extend(brake_report["active_samples"])
        samples.extend(brake_report["torque_off_samples"])
        shutdown_errors.extend(verified_errors)
    except Exception as exc:
        reason = str(exc)
    finally:
        if prepared and not shutdown_attempted:
            brake_report, verified_errors = brake_and_verify_release(
                packet,
                port,
                writer,
                COMM_SUCCESS,
                args.brake_s,
                write_zero=write_wheel_velocities,
                read_wheels=read_wheels,
                stop_readback_confirmed=stop_readback_confirmed,
            )
            samples.extend(brake_report["active_samples"])
            samples.extend(brake_report["torque_off_samples"])
            shutdown_errors.extend(verified_errors)
        try:
            port.closePort()
        except Exception as exc:
            shutdown_errors.append(f"serial close failed: {exc}")

    final_pose = None
    for sample in reversed(samples):
        pose = sample.get("wheel_pose_xy_yaw_deg")
        if isinstance(pose, list):
            final_pose = pose
            break
    status = "PASS" if reason == "wheel_feedback_target_reached" and not shutdown_errors else "FAIL"
    output = {
        "status": status,
        "reason": reason,
        "wheel_ids": list(WHEEL_IDS),
        "command": {
            "direction": args.direction,
            "target_deg": args.target_deg,
            "angular_deg_s": args.angular_deg_s,
            "raw": raw,
            "max_rotate_translation_m": args.max_translation_m,
        },
        "wheel_feedback_final_pose_xy_yaw_deg": final_pose,
        "samples": samples,
        "shutdown_brake": brake_report,
        "shutdown_errors": shutdown_errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**output, "samples": f"{len(samples)} samples written to {args.output}"}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
