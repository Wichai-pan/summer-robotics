#!/usr/bin/env python3
"""Replaceable fake/STS3215 wheel-feedback sources with a hardware-free dry-run."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Callable, Iterable, Mapping, Protocol

try:
    from .base_keyboard import (
        GOAL_VEL,
        MODE_VELOCITY,
        OP_MODE,
        TORQUE,
        WHEEL_IDS,
        require_servo_success,
        write_wheel_velocities,
    )
    from .base_odometry_core import BodyVelocity, WheelFeedback, body_to_wheel_rad_s
except ImportError:
    from base_keyboard import (  # type: ignore
        GOAL_VEL,
        MODE_VELOCITY,
        OP_MODE,
        TORQUE,
        WHEEL_IDS,
        require_servo_success,
        write_wheel_velocities,
    )
    from base_odometry_core import BodyVelocity, WheelFeedback, body_to_wheel_rad_s  # type: ignore


DEFAULT_CONFIG = Path("configs/slam/sts3215_wheel_feedback_unresolved.json")


class WheelFeedbackSource(Protocol):
    def samples(self) -> Iterable[WheelFeedback]: ...


def shutdown_wheels(packet: object, port: object, communication_success: int) -> list[str]:
    """Attempt zero and torque-off for every wheel, returning all failures."""
    errors: list[str] = []
    for motor_id in WHEEL_IDS:
        try:
            communication = packet.write2ByteTxOnly(port, motor_id, GOAL_VEL, 0)
            packet_error = 0
            if communication != communication_success or packet_error != 0:
                errors.append(f"zero ID {motor_id}: comm={communication} error={packet_error}")
        except Exception as exc:
            errors.append(f"zero ID {motor_id}: {exc}")
    for motor_id in WHEEL_IDS:
        try:
            communication = packet.write1ByteTxOnly(port, motor_id, TORQUE, 0)
            packet_error = 0
            if communication != communication_success or packet_error != 0:
                errors.append(f"torque-off ID {motor_id}: comm={communication} error={packet_error}")
        except Exception as exc:
            errors.append(f"torque-off ID {motor_id}: {exc}")
    return errors


def prepare_verified_wheels_stopped(
    packet: object,
    port: object,
    communication_success: int,
    group_sync_write_factory: object,
) -> object:
    """Clear all targets before torque without changing servo operating modes."""
    for motor_id in WHEEL_IDS:
        mode, communication, packet_error = packet.read1ByteTxRx(port, motor_id, OP_MODE)
        require_servo_success(
            "read operating mode",
            motor_id,
            communication,
            packet_error,
            communication_success,
        )
        if mode != MODE_VELOCITY:
            raise RuntimeError(
                f"ID {motor_id} is not in verified velocity mode; refusing to change mode"
            )

    writer = group_sync_write_factory(port, packet, GOAL_VEL, 2)
    write_wheel_velocities(writer, [0, 0, 0], communication_success)
    for motor_id in WHEEL_IDS:
        communication, packet_error = packet.write1ByteTxRx(port, motor_id, TORQUE, 1)
        require_servo_success(
            "enable torque",
            motor_id,
            communication,
            packet_error,
            communication_success,
        )
    return writer


@dataclass
class FakeWheelFeedbackSource:
    body_velocity: BodyVelocity
    duration_s: float = 1.0
    rate_hz: float = 20.0
    start_s: float = 100.0

    def samples(self) -> Iterable[WheelFeedback]:
        wheels = body_to_wheel_rad_s(self.body_velocity)
        count = int(round(self.duration_s * self.rate_hz)) + 1
        for index in range(count):
            timestamp = self.start_s + index / self.rate_hz
            yield WheelFeedback(
                timestamp,
                dict(zip(WHEEL_IDS, wheels)),
                received_monotonic_s=timestamp,
            )


@dataclass(frozen=True)
class RawWheelFeedback:
    sample_monotonic_s: float
    received_monotonic_s: float
    position_raw: dict[int, int]
    velocity_raw: dict[int, int]
    status_raw: dict[int, int]
    moving_raw: dict[int, int]
    velocity_unit_factor_raw: dict[int, int]


def load_sts_config(path: Path, require_resolved: bool) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "forestbridge/slam/sts3215-wheel-feedback/v1":
        raise ValueError("unsupported STS3215 feedback config schema")
    if data.get("motor_ids") != WHEEL_IDS:
        raise ValueError(f"motor_ids must be exactly {WHEEL_IDS}")
    velocity = data.get("present_velocity", {})
    if velocity != {"address": 58, "bytes": 2, "encoding": "sign-magnitude-bit-15"}:
        raise ValueError("Present_Velocity contract does not match pinned LeRobot")
    factor = data.get("velocity_unit_rad_s_per_raw")
    if factor is not None and (not isinstance(factor, (int, float)) or not math.isfinite(factor) or factor <= 0):
        raise ValueError("velocity_unit_rad_s_per_raw must be a positive finite number")
    expected_factor = data.get("expected_velocity_unit_factor_raw")
    if expected_factor is not None and (
        not isinstance(expected_factor, int) or not 0 <= expected_factor <= 255
    ):
        raise ValueError("expected_velocity_unit_factor_raw must be a byte")
    for field in ("pose_covariance_diagonal", "twist_covariance_diagonal"):
        diagonal = data.get(field)
        if diagonal is not None and (
            not isinstance(diagonal, list)
            or len(diagonal) != 6
            or not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in diagonal)
        ):
            raise ValueError(f"{field} must contain six positive finite values")
    for field in (
        "expected_feedback_hz",
        "max_gap_s",
        "max_age_s",
        "max_wheel_speed_rad_s",
        "max_wheel_accel_rad_s2",
        "serial_read_timeout_s",
    ):
        value = data.get(field)
        if value is not None and (
            not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
        ):
            raise ValueError(f"{field} must be a positive finite number")
    if require_resolved and (
        data.get("status") != "verified"
        or factor is None
        or expected_factor is None
        or data.get("expected_feedback_hz") is None
        or data.get("pose_covariance_diagonal") is None
        or data.get("twist_covariance_diagonal") is None
        or data.get("position_cross_turn_behavior") not in ("wraps-4096", "continuous-signed")
        or not isinstance(data.get("feedback_sign_by_id"), dict)
        or set(data["feedback_sign_by_id"]) != {"7", "8", "9"}
        or set(data["feedback_sign_by_id"].values()) - {-1, 1}
        or data.get("max_gap_s") is None
        or data.get("max_age_s") is None
        or data.get("max_wheel_speed_rad_s") is None
        or data.get("max_wheel_accel_rad_s2") is None
        or data.get("serial_read_timeout_s") is None
    ):
        raise ValueError("STS3215 feedback units are unresolved; live mode is blocked")
    return data


class STS3215RawFeedbackSource:
    """Read raw wheel registers without torque, mode, EEPROM, or goal writes."""

    def __init__(
        self,
        port: str,
        rate_hz: float = 30.0,
        command_provider: Callable[[], Mapping[int, int]] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        serial_timeout_s: float = 1.0,
    ) -> None:
        self.port = port
        self.rate_hz = rate_hz
        self.command_provider = command_provider
        self.stop_requested = stop_requested or (lambda: False)
        if not math.isfinite(serial_timeout_s) or serial_timeout_s <= 0:
            raise ValueError("serial_timeout_s must be positive and finite")
        self.serial_timeout_s = serial_timeout_s

    @staticmethod
    def _decode_sign_magnitude(raw: int) -> int:
        return -(raw & 0x7FFF) if raw & 0x8000 else raw & 0x7FFF

    def samples(self) -> Iterable[RawWheelFeedback]:
        from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler

        port = PortHandler(self.port)
        packet = PacketHandler(0)
        timeout_ms = self.serial_timeout_s * 1000.0

        def bounded_packet_timeout(handler: object, _packet_length: int) -> None:
            handler.setPacketTimeoutMillis(timeout_ms)

        port.setPacketTimeout = bounded_packet_timeout.__get__(port, type(port))
        if not port.openPort() or not port.setBaudRate(1_000_000):
            port.closePort()
            raise RuntimeError(f"could not open STS3215 bus {self.port}")
        try:
            period = 1.0 / self.rate_hz
            unit_factor: dict[int, int] = {}
            for motor_id in WHEEL_IDS:
                raw, communication, packet_error = packet.read1ByteTxRx(port, motor_id, 82)
                if communication != COMM_SUCCESS or packet_error != 0:
                    raise RuntimeError(f"Velocity_Unit_factor read failed for ID {motor_id}")
                unit_factor[motor_id] = raw
            command_writer = None
            if self.command_provider is not None:
                command_writer = prepare_verified_wheels_stopped(
                    packet, port, COMM_SUCCESS, GroupSyncWrite
                )
            while not self.stop_requested():
                started = time.monotonic()
                if self.command_provider is not None:
                    commands = self.command_provider()
                    if set(commands) != set(WHEEL_IDS):
                        raise RuntimeError("command provider must return exactly IDs 7/8/9")
                    assert command_writer is not None
                    encoded = [
                        abs(int(commands[motor_id]))
                        | (0x8000 if int(commands[motor_id]) < 0 else 0)
                        for motor_id in WHEEL_IDS
                    ]
                    write_wheel_velocities(command_writer, encoded, COMM_SUCCESS)
                positions: dict[int, int] = {}
                velocities: dict[int, int] = {}
                statuses: dict[int, int] = {}
                moving: dict[int, int] = {}
                for motor_id in WHEEL_IDS:
                    packed, communication, packet_error = packet.read4ByteTxRx(port, motor_id, 56)
                    if communication != COMM_SUCCESS or packet_error != 0:
                        raise RuntimeError(f"position/velocity read failed for ID {motor_id}")
                    status, communication, packet_error = packet.read1ByteTxRx(port, motor_id, 65)
                    if communication != COMM_SUCCESS or packet_error != 0:
                        raise RuntimeError(f"Status read failed for ID {motor_id}")
                    is_moving, communication, packet_error = packet.read1ByteTxRx(port, motor_id, 66)
                    if communication != COMM_SUCCESS or packet_error != 0:
                        raise RuntimeError(f"Moving read failed for ID {motor_id}")
                    positions[motor_id] = packed & 0xFFFF
                    velocities[motor_id] = self._decode_sign_magnitude((packed >> 16) & 0xFFFF)
                    statuses[motor_id] = status
                    moving[motor_id] = is_moving
                received = time.monotonic()
                yield RawWheelFeedback(
                    started,
                    received,
                    positions,
                    velocities,
                    statuses,
                    moving,
                    unit_factor,
                )
                time.sleep(max(0.0, period - (time.monotonic() - started)))
        finally:
            errors: list[str] = []
            if self.command_provider is not None:
                errors = shutdown_wheels(packet, port, COMM_SUCCESS)
            port.closePort()
            if errors:
                raise RuntimeError("wheel shutdown incomplete: " + "; ".join(errors))


class STS3215WheelFeedbackSource:
    """Verified physical-unit wrapper around the same read-only raw source."""

    def __init__(
        self,
        port: str,
        config: dict,
        rate_hz: float = 30.0,
        command_provider: Callable[[], Mapping[int, int]] | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        if config.get("motor_ids") != WHEEL_IDS:
            raise ValueError("only white-board wheel IDs 7/8/9 are allowed")
        factor = config.get("velocity_unit_rad_s_per_raw")
        if config.get("status") != "verified" or factor is None:
            raise ValueError("STS3215 feedback units are unresolved; refusing live source")
        self.port = port
        self.factor = float(factor)
        self.expected_unit_factor = int(config["expected_velocity_unit_factor_raw"])
        self.feedback_sign = {
            int(motor_id): int(sign) for motor_id, sign in config["feedback_sign_by_id"].items()
        }
        self.rate_hz = rate_hz
        self.command_provider = command_provider
        self.stop_requested = stop_requested
        self.serial_timeout_s = float(config["serial_read_timeout_s"])
        if self.serial_timeout_s * 12 >= 0.25:
            raise ValueError("verified serial timeout cannot satisfy the 250 ms command dead-man")

    @staticmethod
    def _decode_sign_magnitude(raw: int) -> int:
        return -(raw & 0x7FFF) if raw & 0x8000 else raw & 0x7FFF

    def samples(self) -> Iterable[WheelFeedback]:
        raw_source = STS3215RawFeedbackSource(
            self.port,
            self.rate_hz,
            command_provider=self.command_provider,
            stop_requested=self.stop_requested,
            serial_timeout_s=self.serial_timeout_s,
        )
        for raw in raw_source.samples():
            if set(raw.velocity_unit_factor_raw.values()) != {self.expected_unit_factor}:
                raise RuntimeError("live Velocity_Unit_factor differs from verified config")
            values = {
                motor_id: raw.velocity_raw[motor_id] * self.factor * self.feedback_sign[motor_id]
                for motor_id in WHEEL_IDS
            }
            yield WheelFeedback(
                raw.sample_monotonic_s,
                values,
                received_monotonic_s=raw.received_monotonic_s,
                raw_position=raw.position_raw,
                raw_velocity=raw.velocity_raw,
                status=raw.status_raw,
                moving=raw.moving_raw,
                velocity_unit_factor_raw=raw.velocity_unit_factor_raw,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-live", action="store_true")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--port")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sum((args.validate_live, args.dry_run, args.pilot)) != 1:
        raise SystemExit("choose exactly one of --dry-run, --validate-live, or --pilot")
    if args.validate_live:
        load_sts_config(args.config, require_resolved=True)
        print("PASS STS3215 feedback config is eligible for a locked live source")
        return 0
    if args.pilot:
        if args.output is None or args.duration <= 0:
            raise SystemExit("--pilot requires --output and positive --duration")
        from portutil import BOARDS, resolve_port

        if input("Read-only IDs 7/8/9 pilot; no motor writes. Type READ: ").strip() != "READ":
            raise SystemExit("pilot cancelled")
        port = resolve_port(BOARDS["white"], override=args.port)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        count = 0
        with args.output.open("x", encoding="utf-8") as stream:
            for sample in STS3215RawFeedbackSource(port).samples():
                stream.write(json.dumps(sample.__dict__, sort_keys=True) + "\n")
                stream.flush()
                count += 1
                if sample.received_monotonic_s - started >= args.duration:
                    break
        print(f"PASS read-only pilot samples={count} output={args.output}")
        return 0
    if not args.dry_run:
        raise SystemExit("this entry is inert unless --dry-run or --validate-live is selected")
    data = load_sts_config(args.config, require_resolved=False)
    print(f"PASS feedback config parsed; status={data['status']}")
    if data["status"] != "verified":
        print("LIVE BLOCKED: velocity unit, refresh rate, and cross-turn behavior need measurement")
    print(f"fake samples={len(list(FakeWheelFeedbackSource(BodyVelocity(0.1, 0.0, 0.0)).samples()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
