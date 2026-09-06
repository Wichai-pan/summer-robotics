#!/usr/bin/env python3
"""Command zero velocity, disable all three wheel torques, and verify readback."""

from __future__ import annotations

import json
import os
import time


def disable_each_wheel(packet: object, port: object, wheel_ids: list[int], torque_register: int, success: int) -> list[str]:
    """A failed wheel must never prevent stop attempts on the other wheels."""
    errors: list[str] = []
    for motor_id in wheel_ids:
        try:
            communication, packet_error = packet.write1ByteTxRx(port, motor_id, torque_register, 0)
            if communication != success or packet_error:
                errors.append(
                    f"disable torque ID {motor_id}: communication={communication}, packet_error={packet_error}"
                )
        except Exception as exc:
            errors.append(f"disable torque ID {motor_id}: {exc}")
    return errors


def main() -> int:
    from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler
    from base_keyboard import GOAL_VEL, TORQUE, WHEEL_IDS, write_wheel_velocities
    from base_stop_diagnostic import read_wheels, stop_readback_confirmed
    from portutil import BOARDS, resolve_port

    port_name = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    port = PortHandler(port_name)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        raise SystemExit(f"cannot open white board {port_name}")
    packet = PacketHandler(0)
    writer = GroupSyncWrite(port, packet, GOAL_VEL, 2)
    errors: list[str] = []
    samples: list[dict[str, object]] = []
    try:
        for _ in range(5):
            try:
                write_wheel_velocities(writer, port, [0, 0, 0], COMM_SUCCESS)
            except Exception as exc:
                errors.append(f"zero velocity: {exc}")
            time.sleep(0.05)
        errors.extend(disable_each_wheel(packet, port, WHEEL_IDS, TORQUE, COMM_SUCCESS))
        for _ in range(3):
            samples.append({"phase": "torque_off_observe", **read_wheels(packet, port)})
            time.sleep(0.15)
    finally:
        port.closePort()
    confirmed = stop_readback_confirmed(samples)
    if not confirmed:
        errors.append("three-wheel zero/torque-off readback was not confirmed")
    result = {"status": "PASS" if not errors else "FAIL", "confirmed": confirmed, "errors": errors, "samples": samples}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
