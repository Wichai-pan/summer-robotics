#!/usr/bin/env python3
"""Diagnose whether the base physically stops after an original Nav2-like pulse.

This tool deliberately uses the same ``body_to_wheel_raw()`` conversion as the
first supervised Nav2 trial. It sends a short forward command, then keeps
writing zero velocity while torque remains enabled for a brief braking window,
reads wheel state, and only then releases torque. It never opens Gemini and
never commands white-arm IDs 1--6.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

# Keep these register constants local so the stop-confirmation predicate can
# be imported and tested without a serial SDK. They match base_keyboard.py.
WHEEL_IDS = [7, 8, 9]
GOAL_VEL = 46
TORQUE = 40
# Protocol-0 success is the SDK's stable integer value. Keeping the read-only
# decoder importable lets the stop predicate be tested without serial modules.
COMM_SUCCESS = 0
PRESENT_VELOCITY = 58
STOP_VELOCITY_EPS_RAW = 60


def decode_signed_magnitude(value: int) -> int:
    return -(value & 0x7FFF) if value & 0x8000 else value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linear-mps", type=float, default=0.04)
    parser.add_argument("--command-s", type=float, default=0.5)
    parser.add_argument("--brake-s", type=float, default=0.8)
    parser.add_argument("--observe-s", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=Path("/data/slam/base-stop-diagnostic.json"))
    return parser.parse_args()


def read_wheels(packet: PacketHandler, port: PortHandler) -> dict[str, object]:
    record: dict[str, object] = {"time_monotonic_s": time.monotonic(), "wheels": {}}
    wheels: dict[str, object] = record["wheels"]  # type: ignore[assignment]
    for motor_id in WHEEL_IDS:
        wheel: dict[str, object] = {}
        for label, address, width in (
            ("goal_velocity_raw", GOAL_VEL, 2),
            ("present_velocity_raw", PRESENT_VELOCITY, 2),
            ("torque_enable", TORQUE, 1),
        ):
            try:
                if width == 2:
                    value, communication, packet_error = packet.read2ByteTxRx(port, motor_id, address)
                else:
                    value, communication, packet_error = packet.read1ByteTxRx(port, motor_id, address)
                if communication != COMM_SUCCESS or packet_error != 0:
                    wheel[label] = {"read_error": f"communication={communication}, packet_error={packet_error}"}
                else:
                    wheel[label] = int(value)
            except Exception as exc:
                wheel[label] = {"read_error": str(exc)}
        present = wheel.get("present_velocity_raw")
        if isinstance(present, int):
            wheel["present_velocity_signed_raw"] = decode_signed_magnitude(present)
        wheels[str(motor_id)] = wheel
    return record


def stop_readback_confirmed(samples: list[dict[str, object]]) -> bool:
    """Require three torque-off observations with zero goal and small wheel speed."""
    observations = [sample for sample in samples if sample.get("phase") == "torque_off_observe"][-3:]
    if len(observations) < 3:
        return False
    for observation in observations:
        wheels = observation.get("wheels")
        if not isinstance(wheels, dict):
            return False
        for motor_id in WHEEL_IDS:
            wheel = wheels.get(str(motor_id))
            if not isinstance(wheel, dict):
                return False
            if wheel.get("goal_velocity_raw") != 0 or wheel.get("torque_enable") != 0:
                return False
            velocity = wheel.get("present_velocity_signed_raw")
            # The idle STS3215 feedback on this base quantizes around +/-50
            # raw. Treat that as stopped; it is far below the +/-450 raw
            # forward command used by this diagnostic.
            if not isinstance(velocity, int) or abs(velocity) > STOP_VELOCITY_EPS_RAW:
                return False
    return True


def main() -> int:
    args = parse_args()
    if not 0 < args.linear_mps <= 0.04:
        raise SystemExit("--linear-mps must be in (0, 0.04] for this diagnostic")
    if not 0 < args.command_s <= 2.0 or not 0 < args.brake_s <= 1.0 or not 0 < args.observe_s <= 3.0:
        raise SystemExit("command/brake/observe durations exceed this diagnostic's safety bounds")
    from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler

    from base_keyboard import (
        body_to_wheel_raw,
        encode_sm,
        prepare_wheels_stopped,
        write_wheel_velocities,
    )
    from nav2_supervised_base_execute import brake_and_verify_release
    from portutil import BOARDS, PortResolutionError, resolve_port

    try:
        port_name = resolve_port(BOARDS["white"], override=os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    port = PortHandler(port_name)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        raise SystemExit(f"cannot open white board {port_name}")
    packet = PacketHandler(0)
    writer = GroupSyncWrite(port, packet, GOAL_VEL, 2)
    samples: list[dict[str, object]] = []
    shutdown_errors: list[str] = []
    raw: list[int] = []
    brake_report: dict[str, Any] = {
        "attempted": False,
        "active_samples": [],
        "torque_off_samples": [],
    }
    prepared = False
    shutdown_attempted = False
    try:
        missing = []
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(port, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                missing.append(motor_id)
        if missing:
            raise RuntimeError(f"base motor IDs did not respond: {missing}; no torque enabled")

        raw = body_to_wheel_raw(args.linear_mps, 0.0, 0.0)
        print(f"Original Nav2 forward conversion: {args.linear_mps:.3f} m/s -> {dict(zip(WHEEL_IDS, raw))}")
        answer = input(
            f"Clear the front route; this sends forward for {args.command_s:.1f}s only. "
            "Hold 12 V cutoff and type DIAGNOSE: "
        ).strip()
        if answer != "DIAGNOSE":
            print("Cancelled before wheel torque.")
            return 2

        # Set this before the first torque-enable write. If preparation partly
        # succeeds, finally must still run the verified all-wheel shutdown.
        prepared = True
        prepare_wheels_stopped(packet, port, COMM_SUCCESS, GroupSyncWrite)
        started = time.monotonic()
        while time.monotonic() - started < args.command_s:
            write_wheel_velocities(writer, port, [encode_sm(value) for value in raw], COMM_SUCCESS)
            samples.append({"phase": "command", **read_wheels(packet, port)})
            time.sleep(0.1)

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

        # Keep the old observation period, but make it part of the evidence
        # rather than merely sleeping after a best-effort TxOnly shutdown.
        observe_deadline = time.monotonic() + args.observe_s
        while time.monotonic() < observe_deadline:
            samples.append({"phase": "torque_off_observe", **read_wheels(packet, port)})
            time.sleep(0.2)
        if not stop_readback_confirmed(samples):
            shutdown_errors.append("wheel stop read-back was not confirmed after observation")
    finally:
        if prepared and not shutdown_attempted:
            emergency_report, verified_errors = brake_and_verify_release(
                packet,
                port,
                writer,
                COMM_SUCCESS,
                args.brake_s,
                write_zero=write_wheel_velocities,
                read_wheels=read_wheels,
                stop_readback_confirmed=stop_readback_confirmed,
            )
            brake_report = emergency_report
            samples.extend(emergency_report["active_samples"])
            samples.extend(emergency_report["torque_off_samples"])
            shutdown_errors.extend(verified_errors)
        try:
            port.closePort()
        except Exception as exc:
            shutdown_errors.append(f"serial close failed: {exc}")

    output = {
        "status": "DIAGNOSTIC_COMPLETE" if not shutdown_errors else "STOP_UNVERIFIED",
        "command": {"linear_mps": args.linear_mps, "duration_s": args.command_s},
        "raw_forward": raw,
        "samples": samples,
        "stop_readback_confirmed": stop_readback_confirmed(samples),
        "shutdown_brake": brake_report,
        "shutdown_errors": shutdown_errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**output, "samples": f"{len(samples)} samples written to {args.output}"}, indent=2))
    return 0 if output["status"] == "DIAGNOSTIC_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
