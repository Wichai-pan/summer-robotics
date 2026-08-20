#!/usr/bin/env python3
"""Verify the revised base shutdown sequence without commanding wheel motion.

Live use requires all three wheels raised. The tool verifies that IDs 7/8/9
start in velocity mode with zero goal velocity and torque disabled, asks for a
typed confirmation, briefly enables torque while continuously broadcasting
zero velocity, then disables torque and verifies three spaced readbacks.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any


WHEEL_IDS = (7, 8, 9)
GOAL_VELOCITY = 46
OPERATING_MODE = 33
VELOCITY_MODE = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brake-s", type=float, default=0.8)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/data/slam/base-shutdown-sequence.json"),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not math.isfinite(args.brake_s) or not 0.5 <= args.brake_s <= 1.0:
        raise ValueError("--brake-s must be in [0.5, 1.0]")


def validate_preflight(record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    wheels = record.get("wheels")
    if not isinstance(wheels, dict):
        return ["preflight has no wheel records"]
    for motor_id in WHEEL_IDS:
        wheel = wheels.get(str(motor_id))
        if not isinstance(wheel, dict):
            failures.append(f"ID {motor_id} is missing")
            continue
        expected = {
            "goal_velocity_raw": 0,
            "present_velocity_signed_raw": 0,
            "torque_enable": 0,
            "operating_mode": VELOCITY_MODE,
        }
        for field, expected_value in expected.items():
            value = wheel.get(field)
            if value != expected_value:
                failures.append(
                    f"ID {motor_id} {field}={value!r}; expected {expected_value}"
                )
    return failures


def main() -> int:
    args = parse_args()
    validate_args(args)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "hardware_access": False,
                    "nonzero_velocity_commands": 0,
                    "wheel_ids": list(WHEEL_IDS),
                    "planned_writes": ["zero velocity", "torque enable", "torque disable"],
                    "brake_s": args.brake_s,
                },
                indent=2,
            )
        )
        return 0

    from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler

    from base_keyboard import prepare_wheels_stopped, write_wheel_velocities
    from base_stop_diagnostic import read_wheels, stop_readback_confirmed
    from nav2_supervised_base_execute import brake_and_verify_release
    from portutil import BOARDS, PortResolutionError, resolve_port

    try:
        port_name = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    port = PortHandler(port_name)
    if not port.openPort():
        raise SystemExit(f"cannot open white board {port_name}")
    if not port.setBaudRate(1_000_000):
        port.closePort()
        raise SystemExit(f"cannot configure white board {port_name} baud rate")
    packet = PacketHandler(0)
    writer = GroupSyncWrite(port, packet, GOAL_VELOCITY, 2)
    prepared = False
    shutdown_attempted = False
    reason = "not_started"
    shutdown_errors: list[str] = []
    samples: list[dict[str, Any]] = []
    try:
        preflight = read_wheels(packet, port)
        for motor_id in WHEEL_IDS:
            mode, communication, packet_error = packet.read1ByteTxRx(
                port, motor_id, OPERATING_MODE
            )
            wheel = preflight["wheels"][str(motor_id)]
            wheel["operating_mode"] = (
                int(mode)
                if communication == COMM_SUCCESS and packet_error == 0
                else {
                    "read_error": (
                        f"communication={communication}, packet_error={packet_error}"
                    )
                }
            )
        samples.append({"phase": "preflight", **preflight})
        failures = validate_preflight(preflight)
        if failures:
            raise RuntimeError("unsafe preflight: " + "; ".join(failures))

        answer = input(
            "Wheels must be raised and 12 V cutoff held. This sends ZERO velocity only. "
            "Type VERIFY_STOP: "
        ).strip()
        if answer != "VERIFY_STOP":
            reason = "operator_cancelled_before_writes"
        else:
            # Set this before the first register write. If preparation fails
            # after only some wheels accepted torque-enable, the finally block
            # must still issue best-effort zero and torque-off to every wheel.
            prepared = True
            prepare_wheels_stopped(packet, port, COMM_SUCCESS, GroupSyncWrite)
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
            reason = "stop_verified" if not shutdown_errors else "stop_unverified"
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

    status = "PASS" if reason == "stop_verified" and not shutdown_errors else "FAIL"
    output = {
        "status": status,
        "reason": reason,
        "zero_velocity_only": True,
        "wheel_ids": list(WHEEL_IDS),
        "samples": samples,
        "shutdown_errors": shutdown_errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {**output, "samples": f"{len(samples)} samples written to {args.output}"},
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
