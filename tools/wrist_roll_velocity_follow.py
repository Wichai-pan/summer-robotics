#!/usr/bin/env python3
"""Supervised wrap-safe black -> white wrist-roll follower.

This test deliberately controls only motor 5 (``wrist_roll``).  The black
wrist is torque-free and read-only.  The white wrist runs in velocity mode so
crossing encoder 4095/0 cannot be interpreted as a nearly full-turn position
move.  All other white-arm motors remain torque-free.
"""

from __future__ import annotations

import argparse
import math
import select
import sys
import termios
import time
import tty

from portutil import BOARDS, PortResolutionError, resolve_port


WRIST = "wrist_roll"
ENCODER_TICKS = 4096
DEG_PER_TICK = 360.0 / ENCODER_TICKS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--black-port")
    parser.add_argument("--white-port")
    parser.add_argument("--black-id", default="black_arm")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--max-speed-deg-s", type=float, default=8.0)
    parser.add_argument("--gain-per-s", type=float, default=1.5)
    parser.add_argument("--deadband-deg", type=float, default=1.5)
    parser.add_argument(
        "--max-travel-deg",
        type=float,
        default=60.0,
        help="maximum accumulated wrist travel from the starting pose",
    )
    return parser.parse_args()


def wrapped_tick_delta(current: int, previous: int) -> int:
    """Shortest signed encoder change across a one-turn 0/4095 boundary."""
    half = ENCODER_TICKS // 2
    return (int(current) - int(previous) + half) % ENCODER_TICKS - half


def velocity_command_raw(error_deg: float, gain: float, maximum_deg_s: float, deadband_deg: float) -> int:
    """Convert closed-loop angular error to a bounded signed raw velocity."""
    if abs(error_deg) <= deadband_deg:
        return 0
    deg_s = max(-maximum_deg_s, min(maximum_deg_s, gain * error_deg))
    raw = int(round(deg_s / DEG_PER_TICK))
    if raw == 0:
        raw = 1 if deg_s > 0 else -1
    return raw


def stop_key_pressed() -> bool:
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    return bool(readable and sys.stdin.read(1).lower() in {"q", "\x1b"})


def raw_wrist(bus: object) -> int:
    # Feetech can report a signed value after applying Homing_Offset.  Modulo
    # maps equivalent one-turn representations back to the encoder circle.
    value = int(bus.read("Present_Position", WRIST, normalize=False))
    return value % ENCODER_TICKS


def main() -> int:
    args = parse_args()
    positive = (
        args.duration_s,
        args.fps,
        args.max_speed_deg_s,
        args.gain_per_s,
        args.deadband_deg,
        args.max_travel_deg,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("all timing, gain, speed and travel values must be positive")
    if not sys.stdin.isatty():
        raise SystemExit("interactive TTY required; use jetson_robot_exec.sh --interactive")

    try:
        black_port = resolve_port(BOARDS["black"], override=args.black_port)
        white_port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if black_port == white_port:
        raise SystemExit("black and white ports resolved to the same device")

    from lerobot.motors.feetech import OperatingMode
    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    black = SO100Follower(
        SO100FollowerConfig(port=black_port, id=args.black_id, disable_torque_on_disconnect=True)
    )
    white = SO100Follower(
        SO100FollowerConfig(port=white_port, id=args.white_id, disable_torque_on_disconnect=True)
    )
    black_connected = False
    white_connected = False
    terminal_state = None
    white_wrist_enabled = False
    try:
        print(f"黑臂 wrist leader（只读/松扭矩）：{black_port}")
        print(f"白臂 wrist follower（仅 ID 5 执行）：{white_port}")
        black.bus.connect()
        black_connected = True
        black.bus.disable_torque()
        white.bus.connect()
        white_connected = True
        white.bus.disable_torque()

        # Configure only motor 5. Goal velocity is explicitly zero before its
        # torque is enabled; the other five white motors stay torque-free.
        white.bus.write("Operating_Mode", WRIST, OperatingMode.VELOCITY.value)
        white.bus.write("Goal_Velocity", WRIST, 0, normalize=False)
        if int(white.bus.read("Goal_Velocity", WRIST, normalize=False)) != 0:
            raise RuntimeError("white wrist Goal_Velocity did not read back as zero")

        black_start = raw_wrist(black.bus)
        white_start = raw_wrist(white.bus)
        direction = -1 if args.invert else 1
        print(
            f"启动 raw：black={black_start}, white={white_start}; "
            f"方向={'反向' if args.invert else '同向'}。"
        )
        print(
            "不会做绝对角度对齐，只复制黑腕从当前姿态开始的相对转动；"
            f"白腕速度≤{args.max_speed_deg_s:.1f}°/s，累计行程≤{args.max_travel_deg:.1f}°。"
        )
        print("扶住线缆、清空腕部周围，并保持可以立即切断 12V。")
        if input("输入 WRIST 才只给白臂 ID 5 上扭矩：").strip() != "WRIST":
            print("已取消；白腕没有上扭矩。")
            return 0

        white.bus.enable_torque(WRIST)
        white_wrist_enabled = True
        terminal_state = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())

        black_previous = black_start
        white_previous = white_start
        black_travel_ticks = 0
        white_travel_ticks = 0
        period = 1.0 / args.fps
        started = time.monotonic()
        last_print = -1.0
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            if stop_key_pressed():
                print("\n收到停止键。")
                break

            black_raw = raw_wrist(black.bus)
            white_raw = raw_wrist(white.bus)
            black_step = wrapped_tick_delta(black_raw, black_previous)
            white_step = wrapped_tick_delta(white_raw, white_previous)
            black_previous = black_raw
            white_previous = white_raw

            # A very large one-frame jump means a stale/bad reading; do not let
            # it become a motor command.
            max_feedback_step = int(round(45.0 / DEG_PER_TICK))
            if abs(black_step) > max_feedback_step or abs(white_step) > max_feedback_step:
                raise RuntimeError(
                    f"implausible encoder jump: black={black_step}, white={white_step} ticks"
                )
            black_travel_ticks += black_step
            white_travel_ticks += white_step
            target_travel_deg = direction * black_travel_ticks * DEG_PER_TICK
            actual_travel_deg = white_travel_ticks * DEG_PER_TICK
            if abs(target_travel_deg) > args.max_travel_deg:
                print(
                    f"\n到达测试行程边界：leader 请求 {target_travel_deg:+.1f}°，"
                    f"限制为 ±{args.max_travel_deg:.1f}°；正常停止。"
                )
                break
            if abs(actual_travel_deg) > args.max_travel_deg + 10.0:
                raise RuntimeError(
                    f"white wrist traveled {actual_travel_deg:+.1f}°, beyond safety margin"
                )

            error_deg = target_travel_deg - actual_travel_deg
            velocity_raw = velocity_command_raw(
                error_deg,
                args.gain_per_s,
                args.max_speed_deg_s,
                args.deadband_deg,
            )
            white.bus.write("Goal_Velocity", WRIST, velocity_raw, normalize=False)

            elapsed = time.monotonic() - started
            if elapsed - last_print >= 0.25:
                print(
                    f"\r{elapsed:5.1f}s leaderΔ={target_travel_deg:+6.1f}° "
                    f"whiteΔ={actual_travel_deg:+6.1f}° error={error_deg:+5.1f}° "
                    f"vel_raw={velocity_raw:+4d}",
                    end="",
                    flush=True,
                )
                last_print = elapsed

            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
        print("\n腕部测试结束。")
        return 0
    except KeyboardInterrupt:
        print("\nCtrl-C：停止白腕。")
        return 130
    finally:
        if terminal_state is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, terminal_state)
        if white_connected:
            try:
                white.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
            except Exception as exc:
                print(f"警告：白腕零速度写入失败，请立即切断 12V：{exc}", file=sys.stderr)
            if white_wrist_enabled:
                try:
                    white.bus.disable_torque(WRIST, num_retry=3)
                    print("白腕已发送零速度并松扭矩。")
                except Exception as exc:
                    print(f"警告：白腕松扭矩失败，请立即切断 12V：{exc}", file=sys.stderr)
            try:
                white.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            except Exception:
                pass
            white.bus.disconnect(disable_torque=False)
        if black_connected:
            black.bus.disconnect(disable_torque=False)


if __name__ == "__main__":
    raise SystemExit(main())
