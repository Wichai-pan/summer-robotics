#!/usr/bin/env python3
"""Read-only comparison of cached SO-100 calibration and motor registers."""

from __future__ import annotations

import argparse
import json

from portutil import BOARDS, PortResolutionError, resolve_port


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("white", "black"), default="white")
    parser.add_argument("--robot-id", default="white_arm_leader_follow")
    parser.add_argument("--port")
    args = parser.parse_args()

    try:
        port = resolve_port(BOARDS[args.arm], override=args.port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    robot = SO100Follower(
        SO100FollowerConfig(
            port=port,
            id=args.robot_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )
    connected = False
    try:
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        expected = robot.calibration
        actual = robot.bus.read_calibration()
        differences: dict[str, dict[str, object]] = {}
        for motor in sorted(set(expected) | set(actual)):
            cached = expected.get(motor)
            observed = actual.get(motor)
            if cached is None or observed is None:
                differences[motor] = {
                    "cached": cached is not None,
                    "motor": observed is not None,
                }
                continue
            fields = {}
            for field in ("homing_offset", "range_min", "range_max"):
                wanted = getattr(cached, field)
                found = getattr(observed, field)
                if wanted != found:
                    fields[field] = {"cached": wanted, "motor": found}
            if fields:
                differences[motor] = fields

        print(
            json.dumps(
                {
                    "status": "PASS" if not differences else "FAIL",
                    "arm": args.arm,
                    "robot_id": args.robot_id,
                    "port": port,
                    "torque_enabled": False,
                    "differences": differences,
                },
                indent=2,
            )
        )
        return 0 if not differences else 1
    finally:
        if connected:
            try:
                robot.bus.disable_torque(num_retry=3)
            finally:
                robot.bus.disconnect(disable_torque=False)


if __name__ == "__main__":
    raise SystemExit(main())
