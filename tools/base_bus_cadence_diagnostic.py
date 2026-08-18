#!/usr/bin/env python3
"""Compare low- and high-cadence readback on white-board wheel IDs 7/8/9.

The live diagnostic is strictly read-only. It never writes velocity, mode,
EEPROM, or torque registers. Hardware imports are delayed until after
``--dry-run`` so software validation cannot open the serial port.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable


WHEEL_IDS = (7, 8, 9)
GOAL_VELOCITY = 46
PRESENT_VELOCITY = 58
TORQUE_ENABLE = 40
REGISTERS = (
    ("goal_velocity_raw", GOAL_VELOCITY, 2),
    ("present_velocity_raw", PRESENT_VELOCITY, 2),
    ("torque_enable", TORQUE_ENABLE, 1),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="white-board serial override")
    parser.add_argument("--settle-s", type=float, default=2.0)
    parser.add_argument("--low-duration-s", type=float, default=10.0)
    parser.add_argument("--high-duration-s", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=Path("/data/slam/base-bus-cadence.json"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    bounds = {
        "settle_s": (0.5, 5.0),
        "low_duration_s": (2.0, 30.0),
        "high_duration_s": (2.0, 30.0),
    }
    for name, (minimum, maximum) in bounds.items():
        value = getattr(args, name)
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"--{name.replace('_', '-')} must be in [{minimum}, {maximum}]")


def read_cycle(
    packet: Any,
    port: Any,
    communication_success: int,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started = monotonic()
    reads: list[dict[str, Any]] = []
    for motor_id in WHEEL_IDS:
        for label, address, width in REGISTERS:
            read_started = monotonic()
            if width == 2:
                value, communication, packet_error = packet.read2ByteTxRx(port, motor_id, address)
            else:
                value, communication, packet_error = packet.read1ByteTxRx(port, motor_id, address)
            reads.append(
                {
                    "motor_id": motor_id,
                    "register": label,
                    "value": int(value) if communication == communication_success and packet_error == 0 else None,
                    "communication": int(communication),
                    "packet_error": int(packet_error),
                    "latency_s": round(monotonic() - read_started, 6),
                }
            )
    return {
        "started_monotonic_s": started,
        "duration_s": round(monotonic() - started, 6),
        "reads": reads,
    }


def summarize(cycles: list[dict[str, Any]], communication_success: int) -> dict[str, Any]:
    reads = [read for cycle in cycles for read in cycle["reads"]]
    failures = [
        read
        for read in reads
        if read["communication"] != communication_success or read["packet_error"] != 0
    ]
    latencies = [float(read["latency_s"]) for read in reads]
    codes = Counter(str(read["communication"]) for read in reads)
    return {
        "cycles": len(cycles),
        "reads": len(reads),
        "successes": len(reads) - len(failures),
        "failures": len(failures),
        "failure_rate": round(len(failures) / len(reads), 6) if reads else 1.0,
        "communication_codes": dict(sorted(codes.items())),
        "mean_read_latency_s": round(sum(latencies) / len(latencies), 6) if latencies else None,
        "max_read_latency_s": round(max(latencies), 6) if latencies else None,
    }


def run_profile(
    packet: Any,
    port: Any,
    communication_success: int,
    *,
    duration_s: float,
    period_s: float,
) -> list[dict[str, Any]]:
    cycles: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        cycle_started = time.monotonic()
        cycles.append(read_cycle(packet, port, communication_success))
        time.sleep(max(0.0, period_s - (time.monotonic() - cycle_started)))
    return cycles


def preflight_failures(cycles: list[dict[str, Any]], communication_success: int) -> list[str]:
    failures: list[str] = []
    for cycle_index, cycle in enumerate(cycles):
        for read in cycle["reads"]:
            if read["communication"] != communication_success or read["packet_error"] != 0:
                failures.append(
                    f"cycle {cycle_index} ID {read['motor_id']} {read['register']} "
                    f"communication={read['communication']} packet_error={read['packet_error']}"
                )
            elif read["register"] == "torque_enable" and read["value"] != 0:
                failures.append(f"cycle {cycle_index} ID {read['motor_id']} torque is not off")
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
                    "register_writes": 0,
                    "wheel_ids": list(WHEEL_IDS),
                    "settle_s": args.settle_s,
                    "profiles": {"low_period_s": 1.0, "high_period_s": 0.1},
                },
                indent=2,
            )
        )
        return 0

    from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler
    from portutil import BOARDS, PortResolutionError, resolve_port

    try:
        port_name = resolve_port(BOARDS["white"], override=args.port or os.environ.get("XLEROBOT_PORT"))
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    port = PortHandler(port_name)
    if not port.openPort() or not port.setBaudRate(1_000_000):
        raise SystemExit(f"cannot open white board {port_name}")
    packet = PacketHandler(0)
    preflight: list[dict[str, Any]] = []
    low_rate: list[dict[str, Any]] = []
    high_rate: list[dict[str, Any]] = []
    failure: str | None = None
    try:
        time.sleep(args.settle_s)
        for _ in range(3):
            preflight.append(read_cycle(packet, port, COMM_SUCCESS))
            time.sleep(0.5)
        failures = preflight_failures(preflight, COMM_SUCCESS)
        if failures:
            failure = "preflight failed: " + "; ".join(failures[:6])
        else:
            low_rate = run_profile(
                packet,
                port,
                COMM_SUCCESS,
                duration_s=args.low_duration_s,
                period_s=1.0,
            )
            if summarize(low_rate, COMM_SUCCESS)["failures"]:
                failure = "low-rate profile failed; high-rate profile was not attempted"
            else:
                high_rate = run_profile(
                    packet,
                    port,
                    COMM_SUCCESS,
                    duration_s=args.high_duration_s,
                    period_s=0.1,
                )
    finally:
        port.closePort()

    low_summary = summarize(low_rate, COMM_SUCCESS)
    high_summary = summarize(high_rate, COMM_SUCCESS)
    if failure is None and (low_summary["failures"] or high_summary["failures"]):
        failure = "one or more readback transactions timed out or returned a packet error"
    output = {
        "status": "PASS" if failure is None else "FAIL",
        "failure": failure,
        "read_only": True,
        "register_writes": 0,
        "port": port_name,
        "settle_s": args.settle_s,
        "preflight": preflight,
        "profiles": {
            "low_rate": {"period_s": 1.0, "summary": low_summary, "cycles": low_rate},
            "high_rate": {"period_s": 0.1, "summary": high_summary, "cycles": high_rate},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": output["status"],
                "failure": failure,
                "read_only": True,
                "profiles": {
                    "low_rate": low_summary,
                    "high_rate": high_summary,
                },
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0 if failure is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
