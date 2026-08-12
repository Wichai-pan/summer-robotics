#!/usr/bin/env python3
"""Save, inspect, jog and restore the Gemini 335 two-axis gimbal pose.

Only black-board motors 7 and 8 are addressed.  ``read`` and ``save`` never
enable torque or write a motor register.  ``jog`` and ``return`` use a bounded
velocity loop and a shortest-path encoder error, so a target close to encoder
wrap 4095/0 cannot become an almost-full-turn position command.

The physical yaw/pitch mapping is intentionally not guessed.  Use ``jog`` on
one axis at a time, observe the camera, then record the mapping with
``set-axis-map``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler

from portutil import BOARDS, PortResolutionError, resolve_port


BAUD = 1_000_000
MOTOR_IDS = (7, 8)
MODEL_NUMBER = 777
ENCODER_TICKS = 4096
DEG_PER_TICK = 360.0 / ENCODER_TICKS

# STS3215 control table
OPERATING_MODE = 33
TORQUE_ENABLE = 40
GOAL_VELOCITY = 46
PRESENT_POSITION = 56
POSITION_MODE = 0
VELOCITY_MODE = 1

DEFAULT_REFERENCE = Path("/data/config/gemini_gimbal_grasp_pose_v1.json")


def wrapped_tick_delta(target: int, current: int) -> int:
    """Return the shortest signed delta from ``current`` to ``target``."""
    half = ENCODER_TICKS // 2
    return (int(target) - int(current) + half) % ENCODER_TICKS - half


def velocity_raw(error_deg: float, gain: float, max_speed_deg_s: float, deadband_deg: float) -> int:
    """Return signed raw speed; encoding for the servo happens separately."""
    if abs(error_deg) <= deadband_deg:
        return 0
    deg_s = max(-max_speed_deg_s, min(max_speed_deg_s, gain * error_deg))
    raw = int(round(deg_s / DEG_PER_TICK))
    if raw == 0:
        return 1 if deg_s > 0 else -1
    return raw


def encode_sign_magnitude(value: int, sign_bit: int = 15) -> int:
    magnitude = abs(int(value))
    maximum = (1 << sign_bit) - 1
    if magnitude > maximum:
        raise ValueError(f"velocity magnitude {magnitude} exceeds {maximum}")
    return magnitude | ((1 << sign_bit) if value < 0 else 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="override black-board serial device")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("read", help="read both axes; never writes motor registers")

    save = subparsers.add_parser("save", help="save the current pose as the grasp reference")
    save.add_argument("--force", action="store_true", help="overwrite without the SAVE prompt")

    mapping = subparsers.add_parser("set-axis-map", help="record which physical axis uses each motor ID")
    mapping.add_argument("--yaw-id", type=int, choices=MOTOR_IDS, required=True)
    mapping.add_argument("--pitch-id", type=int, choices=MOTOR_IDS, required=True)

    jog = subparsers.add_parser("jog", help="move exactly one axis by a small relative angle")
    jog.add_argument("--id", type=int, choices=MOTOR_IDS, required=True)
    jog.add_argument("--degrees", type=float, required=True)
    add_motion_args(jog)

    restore = subparsers.add_parser("return", help="return both axes to the saved reference")
    add_motion_args(restore)
    return parser.parse_args()


def add_motion_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--max-speed-deg-s", type=float, default=4.0)
    parser.add_argument("--gain-per-s", type=float, default=1.2)
    parser.add_argument("--deadband-deg", type=float, default=0.5)
    parser.add_argument("--final-tolerance-deg", type=float, default=0.5)
    parser.add_argument("--max-travel-deg", type=float, default=120.0)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--execute", action="store_true")


def check_comm(packet: PacketHandler, comm: int, error: int, operation: str) -> None:
    if comm != COMM_SUCCESS:
        raise RuntimeError(f"{operation}: {packet.getTxRxResult(comm)}")
    if error:
        raise RuntimeError(f"{operation}: {packet.getRxPacketError(error)}")


def read_u8(packet: PacketHandler, port: PortHandler, motor_id: int, address: int, name: str) -> int:
    value, comm, error = packet.read1ByteTxRx(port, motor_id, address)
    check_comm(packet, comm, error, f"read {name} from ID {motor_id}")
    return int(value)


def read_u16(packet: PacketHandler, port: PortHandler, motor_id: int, address: int, name: str) -> int:
    value, comm, error = packet.read2ByteTxRx(port, motor_id, address)
    check_comm(packet, comm, error, f"read {name} from ID {motor_id}")
    return int(value) % ENCODER_TICKS


def write_u8(packet: PacketHandler, port: PortHandler, motor_id: int, address: int, value: int, name: str) -> None:
    comm, error = packet.write1ByteTxRx(port, motor_id, address, int(value))
    check_comm(packet, comm, error, f"write {name} on ID {motor_id}")


def write_u16(packet: PacketHandler, port: PortHandler, motor_id: int, address: int, value: int, name: str) -> None:
    comm, error = packet.write2ByteTxRx(port, motor_id, address, int(value))
    check_comm(packet, comm, error, f"write {name} on ID {motor_id}")


def connect_black_board(override: str | None) -> tuple[str, PortHandler, PacketHandler]:
    try:
        device = resolve_port(BOARDS["black"], override=override)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    port = PortHandler(device)
    if not port.openPort():
        raise SystemExit(f"cannot open black-board port {device}; stop other robot programs first")
    if not port.setBaudRate(BAUD):
        port.closePort()
        raise SystemExit(f"cannot set {BAUD} baud on {device}")
    return device, port, PacketHandler(0)


def inspect_axes(packet: PacketHandler, port: PortHandler) -> dict[int, dict[str, int]]:
    axes: dict[int, dict[str, int]] = {}
    for motor_id in MOTOR_IDS:
        model, comm, error = packet.ping(port, motor_id)
        check_comm(packet, comm, error, f"ping ID {motor_id}")
        if int(model) != MODEL_NUMBER:
            raise RuntimeError(f"ID {motor_id} model is {model}, expected {MODEL_NUMBER}")
        axes[motor_id] = {
            "raw": read_u16(packet, port, motor_id, PRESENT_POSITION, "Present_Position"),
            "operating_mode": read_u8(packet, port, motor_id, OPERATING_MODE, "Operating_Mode"),
            "torque_enabled": read_u8(packet, port, motor_id, TORQUE_ENABLE, "Torque_Enable"),
        }
    return axes


def print_axes(device: str, axes: dict[int, dict[str, int]]) -> None:
    print(f"黑板端口：{device}（serial {BOARDS['black']}）")
    for motor_id in MOTOR_IDS:
        axis = axes[motor_id]
        print(
            f"ID {motor_id}: raw={axis['raw']:4d}  "
            f"one-turn={axis['raw'] * DEG_PER_TICK:7.2f}°  "
            f"mode={axis['operating_mode']}  torque={axis['torque_enabled']}"
        )


def load_reference(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"gimbal reference not found: {path}; run the save command first")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "forestbridge/gemini_gimbal_pose/v1":
        raise SystemExit(f"unsupported gimbal reference schema in {path}")
    if data.get("board_serial") != BOARDS["black"]:
        raise SystemExit(f"reference belongs to a different controller: {data.get('board_serial')}")
    raw = data.get("raw_position", {})
    if set(raw) != {"7", "8"}:
        raise SystemExit(f"reference must contain raw positions for ID 7 and 8: {path}")
    return data


def save_reference(path: Path, axes: dict[int, dict[str, int]], force: bool) -> None:
    if path.exists() and not force:
        if not sys.stdin.isatty() or input(f"{path} already exists. Type SAVE to replace it: ").strip() != "SAVE":
            raise SystemExit("cancelled; existing reference was not changed")
    old_mapping: dict[str, Any] = {}
    if path.is_file():
        try:
            old_mapping = json.loads(path.read_text(encoding="utf-8")).get("axis_map", {})
        except (OSError, json.JSONDecodeError):
            old_mapping = {}
    payload = {
        "schema": "forestbridge/gemini_gimbal_pose/v1",
        "purpose": "fixed Gemini pose used by eye-to-hand IK and ACT grasping",
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "board_serial": BOARDS["black"],
        "motor_ids": list(MOTOR_IDS),
        "raw_position": {str(motor_id): axes[motor_id]["raw"] for motor_id in MOTOR_IDS},
        "one_turn_degrees_reference_only": {
            str(motor_id): axes[motor_id]["raw"] * DEG_PER_TICK for motor_id in MOTOR_IDS
        },
        "axis_map": old_mapping or {"yaw_motor_id": None, "pitch_motor_id": None},
        "note": "raw encoder values are authoritative; degrees are display-only and not calibrated world angles",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    print(f"已保存 Gemini 抓取云台姿态：{path}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def set_axis_map(path: Path, yaw_id: int, pitch_id: int) -> None:
    if yaw_id == pitch_id:
        raise SystemExit("yaw and pitch must use different motor IDs")
    data = load_reference(path)
    data["axis_map"] = {"yaw_motor_id": yaw_id, "pitch_motor_id": pitch_id}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    print(f"已记录轴映射：yaw=ID {yaw_id}, pitch=ID {pitch_id}")


def validate_motion_args(args: argparse.Namespace) -> None:
    values = (
        args.fps,
        args.max_speed_deg_s,
        args.gain_per_s,
        args.deadband_deg,
        args.final_tolerance_deg,
        args.max_travel_deg,
        args.timeout_s,
    )
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise SystemExit("all rates, limits, tolerances and timeout must be positive")
    if args.final_tolerance_deg > args.deadband_deg:
        raise SystemExit("final tolerance must be no greater than the zero-velocity deadband")
    if args.execute and not sys.stdin.isatty():
        raise SystemExit("interactive TTY required for --execute")


def move_to_targets(
    packet: PacketHandler,
    port: PortHandler,
    targets: dict[int, int],
    args: argparse.Namespace,
    confirmation: str,
) -> None:
    validate_motion_args(args)
    axes = inspect_axes(packet, port)
    for motor_id in targets:
        if axes[motor_id]["operating_mode"] != POSITION_MODE:
            raise RuntimeError(
                f"ID {motor_id} is in mode {axes[motor_id]['operating_mode']}; "
                "restore position mode before using this tool"
            )
    planned = {
        motor_id: wrapped_tick_delta(target, axes[motor_id]["raw"]) * DEG_PER_TICK
        for motor_id, target in targets.items()
    }
    for motor_id, delta_deg in planned.items():
        if abs(delta_deg) > args.max_travel_deg:
            raise RuntimeError(
                f"ID {motor_id} shortest return is {delta_deg:+.1f}°, exceeding "
                f"limit {args.max_travel_deg:.1f}°"
            )
    print("运动计划（编码器最短路径）：")
    for motor_id in targets:
        print(
            f"  ID {motor_id}: {axes[motor_id]['raw']} -> {targets[motor_id]} "
            f"({planned[motor_id]:+.2f}°)"
        )
    if not args.execute:
        print("DRY RUN：未写寄存器或启用扭矩。添加 --execute 才允许运动。")
        return
    print("只控制黑板 ID 7/8；黑臂 ID 1–6 始终不参与。")
    if input(f"清空云台和线缆活动范围；输入 {confirmation} 执行：").strip() != confirmation:
        print("已取消；没有启用扭矩。")
        return

    active = list(targets)
    previous = {motor_id: axes[motor_id]["raw"] for motor_id in active}
    cumulative_ticks = {motor_id: 0 for motor_id in active}
    stable_cycles = 0
    torque_enabled: list[int] = []
    modes_changed: list[int] = []
    period = 1.0 / args.fps
    started = time.monotonic()
    last_print = -1.0
    try:
        for motor_id in active:
            write_u8(packet, port, motor_id, TORQUE_ENABLE, 0, "Torque_Enable")
            write_u8(packet, port, motor_id, OPERATING_MODE, VELOCITY_MODE, "Operating_Mode")
            modes_changed.append(motor_id)
            write_u16(packet, port, motor_id, GOAL_VELOCITY, 0, "Goal_Velocity")
        for motor_id in active:
            write_u8(packet, port, motor_id, TORQUE_ENABLE, 1, "Torque_Enable")
            torque_enabled.append(motor_id)

        while time.monotonic() - started < args.timeout_s:
            loop_started = time.monotonic()
            errors: dict[int, float] = {}
            for motor_id, target in targets.items():
                now = read_u16(packet, port, motor_id, PRESENT_POSITION, "Present_Position")
                step = wrapped_tick_delta(now, previous[motor_id])
                previous[motor_id] = now
                if abs(step * DEG_PER_TICK) > 20.0:
                    raise RuntimeError(f"implausible feedback jump on ID {motor_id}: {step} ticks")
                cumulative_ticks[motor_id] += step
                if abs(cumulative_ticks[motor_id] * DEG_PER_TICK) > args.max_travel_deg + 5.0:
                    raise RuntimeError(f"ID {motor_id} exceeded the travel safety margin")
                error_deg = wrapped_tick_delta(target, now) * DEG_PER_TICK
                errors[motor_id] = error_deg
                speed = velocity_raw(
                    error_deg,
                    args.gain_per_s,
                    args.max_speed_deg_s,
                    args.deadband_deg,
                )
                write_u16(
                    packet,
                    port,
                    motor_id,
                    GOAL_VELOCITY,
                    encode_sign_magnitude(speed),
                    "Goal_Velocity",
                )
            if all(abs(error) <= args.final_tolerance_deg for error in errors.values()):
                stable_cycles += 1
                if stable_cycles >= 5:
                    break
            else:
                stable_cycles = 0
            elapsed = time.monotonic() - started
            if elapsed - last_print >= 0.5:
                print(
                    "\r"
                    + f"{elapsed:5.1f}s "
                    + " ".join(f"ID{motor_id} error={errors[motor_id]:+6.2f}°" for motor_id in active),
                    end="",
                    flush=True,
                )
                last_print = elapsed
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
        else:
            raise RuntimeError(f"gimbal return timed out after {args.timeout_s:.1f}s")
        print("\n云台达到目标容差。")
    finally:
        for motor_id in active:
            try:
                write_u16(packet, port, motor_id, GOAL_VELOCITY, 0, "Goal_Velocity")
            except Exception as exc:
                print(f"警告：ID {motor_id} 零速度失败，请切断 12V：{exc}", file=sys.stderr)
        for motor_id in torque_enabled:
            try:
                write_u8(packet, port, motor_id, TORQUE_ENABLE, 0, "Torque_Enable")
            except Exception as exc:
                print(f"警告：ID {motor_id} 松扭矩失败，请切断 12V：{exc}", file=sys.stderr)
        for motor_id in modes_changed:
            try:
                write_u8(packet, port, motor_id, OPERATING_MODE, POSITION_MODE, "Operating_Mode")
            except Exception as exc:
                print(f"警告：ID {motor_id} 恢复位置模式失败：{exc}", file=sys.stderr)

    final_axes = inspect_axes(packet, port)
    failures = {
        motor_id: wrapped_tick_delta(target, final_axes[motor_id]["raw"]) * DEG_PER_TICK
        for motor_id, target in targets.items()
        if abs(wrapped_tick_delta(target, final_axes[motor_id]["raw"]) * DEG_PER_TICK)
        > args.final_tolerance_deg
    }
    print_axes("复核", final_axes)
    if failures:
        raise RuntimeError(f"final gimbal verification failed: {failures}")
    print("status=PASS；云台已松扭矩并恢复位置模式。")


def main() -> int:
    args = parse_args()
    if args.command == "set-axis-map":
        set_axis_map(args.reference, args.yaw_id, args.pitch_id)
        return 0

    device, port, packet = connect_black_board(args.port)
    try:
        axes = inspect_axes(packet, port)
        if args.command == "read":
            print_axes(device, axes)
        elif args.command == "save":
            print_axes(device, axes)
            save_reference(args.reference, axes, args.force)
        elif args.command == "jog":
            target = (
                axes[args.id]["raw"]
                + int(round(args.degrees / DEG_PER_TICK))
            ) % ENCODER_TICKS
            move_to_targets(packet, port, {args.id: target}, args, "JOG")
        elif args.command == "return":
            reference = load_reference(args.reference)
            targets = {
                motor_id: int(reference["raw_position"][str(motor_id)]) % ENCODER_TICKS
                for motor_id in MOTOR_IDS
            }
            move_to_targets(packet, port, targets, args, "RETURN")
        else:  # pragma: no cover - argparse enforces the command
            raise AssertionError(args.command)
        return 0
    finally:
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
