#!/usr/bin/env python3
"""Read the white-board wheel velocity configuration without enabling torque.

This probe never changes operating mode, torque, position, velocity or any
EEPROM/SRAM value. It exists to verify the STS3215 Goal_Velocity unit before a
navigation controller is allowed to move the base.
"""

from __future__ import annotations

import os

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler

from base_keyboard import WHEEL_IDS
from portutil import BOARDS, PortResolutionError, resolve_port


VELOCITY_UNIT_FACTOR = 82
TORQUE_ENABLE = 40
GOAL_VELOCITY = 46
PRESENT_VELOCITY = 58


def main() -> int:
    try:
        port = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    handler = PortHandler(port)
    if not handler.openPort() or not handler.setBaudRate(1_000_000):
        raise SystemExit(f"cannot open white board {port}")
    packet = PacketHandler(0)
    try:
        print(f"White board: {port}; read-only wheel velocity-unit check")
        units: dict[int, int] = {}
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(handler, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                raise RuntimeError(f"wheel {motor_id} did not respond")
            unit, communication, packet_error = packet.read1ByteTxRx(handler, motor_id, VELOCITY_UNIT_FACTOR)
            if communication != COMM_SUCCESS or packet_error != 0:
                raise RuntimeError(f"cannot read Velocity_Unit_factor from wheel {motor_id}")
            torque, _, _ = packet.read1ByteTxRx(handler, motor_id, TORQUE_ENABLE)
            goal, _, _ = packet.read2ByteTxRx(handler, motor_id, GOAL_VELOCITY)
            present, _, _ = packet.read2ByteTxRx(handler, motor_id, PRESENT_VELOCITY)
            units[motor_id] = int(unit)
            print(
                f"ID {motor_id}: Velocity_Unit_factor={unit}; torque={torque}; "
                f"goal_raw={goal}; present_raw={present}"
            )
        expected = {50}
        print("status=PASS" if set(units.values()) == expected else f"status=CHECK units={units}")
        return 0
    finally:
        handler.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
