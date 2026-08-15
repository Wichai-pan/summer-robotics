#!/usr/bin/env python3
"""Find the minimum safe wheel raw command that starts the base moving.

This is a supervised physical calibration, not navigation. Each candidate is a
single forward pulse with wheel commands ``[-raw, 0, +raw]`` (the established
W/forward mapping), then zero velocity and torque-off. It never commands white
arm IDs 1--6. Start at raw 10 and stop at the first clearly moving candidate.
"""

from __future__ import annotations

import argparse
import os
import time

from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler

from base_keyboard import (
    GOAL_VEL,
    TORQUE,
    WHEEL_IDS,
    encode_sm,
    prepare_wheels_stopped,
    write_wheel_velocities,
)
from portutil import BOARDS, PortResolutionError, resolve_port


VELOCITY_UNIT_FACTOR = 82


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-values", type=int, nargs="+", default=[10, 15, 20, 25, 30])
    parser.add_argument("--pulse-s", type=float, default=0.4)
    return parser.parse_args()


def disable_wheels(packet: PacketHandler, port: PortHandler) -> list[str]:
    """Send stop/release without waiting for an unreliable wheel status reply."""
    errors: list[str] = []
    for motor_id in WHEEL_IDS:
        for address, value, label, width in (
            (GOAL_VEL, 0, "zero", 2),
            (TORQUE, 0, "torque off", 1),
        ):
            try:
                if width == 2:
                    communication = packet.write2ByteTxOnly(port, motor_id, address, value)
                else:
                    communication = packet.write1ByteTxOnly(port, motor_id, address, value)
                if communication != COMM_SUCCESS:
                    errors.append(f"{label} ID {motor_id} failed")
            except Exception as exc:
                errors.append(f"{label} ID {motor_id}: {exc}")
    return errors


def main() -> int:
    args = parse_args()
    if not 0 < args.pulse_s <= 0.5:
        raise SystemExit("--pulse-s must be in (0, 0.5] for this first calibration")
    if not args.raw_values or any(value < 1 or value > 30 for value in args.raw_values):
        raise SystemExit("--raw-values must be within 1..30 for this first calibration")
    try:
        port_name = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    port = PortHandler(port_name)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        raise SystemExit(f"cannot open white board {port_name}")
    packet = PacketHandler(0)
    writer = GroupSyncWrite(port, packet, GOAL_VEL, 2)
    try:
        units = {}
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(port, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                raise RuntimeError(f"wheel {motor_id} did not respond; no pulse will be sent")
            unit, communication, packet_error = packet.read1ByteTxRx(port, motor_id, VELOCITY_UNIT_FACTOR)
            if communication != COMM_SUCCESS or packet_error != 0:
                raise RuntimeError(f"cannot read Velocity_Unit_factor on wheel {motor_id}")
            units[motor_id] = int(unit)
        if len(set(units.values())) != 1:
            raise RuntimeError(f"wheel Velocity_Unit_factor values disagree: {units}; no pulse will be sent")

        print("Forward-only static-friction calibration. White arm IDs 1--6 are never commanded.")
        print(f"Wheel velocity-unit register: {units}. Each pulse lasts {args.pulse_s:.1f}s then releases torque.")
        for raw in args.raw_values:
            answer = input(
                f"Clear front route; candidate raw={raw}. "
                "Type PULSE to run one forward pulse, or anything else to stop: "
            ).strip()
            if answer != "PULSE":
                print("Stopped before next pulse. All wheel torque remains off.")
                return 0
            prepare_wheels_stopped(packet, port, COMM_SUCCESS, GroupSyncWrite)
            write_wheel_velocities(writer, port, [encode_sm(-raw), 0, encode_sm(raw)], COMM_SUCCESS)
            time.sleep(args.pulse_s)
            errors = disable_wheels(packet, port)
            if errors:
                raise RuntimeError("; ".join(errors))
            print(f"raw={raw} finished; base is stopped and torque-free. Observe its displacement before continuing.")
    finally:
        errors = disable_wheels(packet, port)
        port.closePort()
        if errors:
            print("WARNING: shutdown errors: " + "; ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
