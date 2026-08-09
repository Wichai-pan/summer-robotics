#!/usr/bin/env python3
"""Supervised, bounded black-arm -> white-arm leader/follower smoke test.

The black arm is always torque-free and read only.  The white arm mirrors
*relative* motion around both arms' startup poses.  This avoids assuming that
their calibrated zero positions are identical.  The default total excursion
is deliberately small; widen it only after checking every joint direction.
"""

from __future__ import annotations

import argparse
import select
import sys
import termios
import time
import tty

from portutil import BOARDS, PortResolutionError, resolve_port


JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded black-arm leader -> white-arm follower test"
    )
    parser.add_argument("--black-port", help="optional black-board port override")
    parser.add_argument("--white-port", help="optional white-board port override")
    parser.add_argument(
        "--black-id",
        default="black_arm",
        help="LeRobot calibration id for the hand-moved black arm",
    )
    parser.add_argument(
        "--white-id",
        default="white_arm_xlerobot",
        help="LeRobot calibration id for the powered white arm",
    )
    parser.add_argument(
        "--invert",
        nargs="*",
        choices=JOINTS,
        default=[],
        help="joints whose relative motion should be sign-inverted",
    )
    parser.add_argument(
        "--max-delta-deg",
        type=float,
        default=5.0,
        help="maximum total white-arm displacement from startup for arm joints",
    )
    parser.add_argument(
        "--max-gripper-delta",
        type=float,
        default=10.0,
        help="maximum total gripper displacement from startup (0-100 units)",
    )
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument(
        "--tracking-error-deg",
        type=float,
        default=12.0,
        help="abort when a commanded arm joint cannot track within this error",
    )
    return parser.parse_args()


def positions(observation: dict[str, object]) -> dict[str, float]:
    result = {
        key.removesuffix(".pos"): float(value)
        for key, value in observation.items()
        if key.endswith(".pos")
    }
    missing = [joint for joint in JOINTS if joint not in result]
    if missing:
        raise RuntimeError(f"missing joint observations: {missing}")
    return result


def bounded_relative_targets(
    black_now: dict[str, float],
    black_start: dict[str, float],
    white_start: dict[str, float],
    signs: dict[str, float],
    max_delta_deg: float,
    max_gripper_delta: float,
) -> dict[str, float]:
    targets: dict[str, float] = {}
    for joint in JOINTS:
        limit = max_gripper_delta if joint == "gripper" else max_delta_deg
        relative = signs[joint] * (black_now[joint] - black_start[joint])
        relative = max(-limit, min(limit, relative))
        target = white_start[joint] + relative
        if joint == "gripper":
            target = max(0.0, min(100.0, target))
        targets[f"{joint}.pos"] = target
    return targets


def key_available() -> bool:
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return False
    return sys.stdin.read(1).lower() in {"q", "\x1b"}


def configure_follower_while_torque_off(robot: object) -> None:
    """Apply the normal SO follower settings without re-enabling torque."""
    from lerobot.motors.feetech import OperatingMode

    bus = robot.bus
    bus.disable_torque()
    bus.configure_motors()
    for motor in bus.motors:
        bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
        bus.write("P_Coefficient", motor, 16)
        bus.write("I_Coefficient", motor, 0)
        bus.write("D_Coefficient", motor, 32)
        if motor == "gripper":
            bus.write("Max_Torque_Limit", motor, 500)
            bus.write("Protection_Current", motor, 250)
            bus.write("Overload_Torque", motor, 25)


def main() -> int:
    args = parse_args()
    if args.max_delta_deg <= 0 or args.max_gripper_delta <= 0:
        raise SystemExit("motion limits must be positive")
    if args.fps <= 0 or args.duration_s <= 0:
        raise SystemExit("fps and duration must be positive")
    if not sys.stdin.isatty():
        raise SystemExit("interactive TTY required; use jetson_robot_exec.sh --interactive")

    try:
        black_port = resolve_port(BOARDS["black"], override=args.black_port)
        white_port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if black_port == white_port:
        raise SystemExit("black and white ports resolved to the same device")

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    black = SO100Follower(
        SO100FollowerConfig(
            port=black_port,
            id=args.black_id,
            disable_torque_on_disconnect=True,
        )
    )
    white = SO100Follower(
        SO100FollowerConfig(
            port=white_port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target={
                joint: (2.0 if joint == "gripper" else 1.0) for joint in JOINTS
            },
        )
    )

    black_connected = False
    white_connected = False
    saved_terminal = None
    try:
        print(f"黑臂 leader（只读/松扭矩）：{black_port}")
        print(f"白臂 follower（执行）：{white_port}")
        # Connect buses directly. SOFollower.connect() calls configure(), whose
        # torque-disabled context re-enables torque on exit; that is unsuitable
        # for a hand-moved leader and for a follower awaiting confirmation.
        black.bus.connect()
        black_connected = True
        black.bus.disable_torque()
        if not black.is_calibrated:
            raise RuntimeError(
                f"black-arm motor registers do not match {args.black_id} calibration"
            )

        white.bus.connect()
        white_connected = True
        white.bus.disable_torque()
        if not white.is_calibrated:
            raise RuntimeError(
                f"white-arm motor registers do not match {args.white_id} calibration"
            )
        configure_follower_while_torque_off(white)

        black_start = positions(black.get_observation())
        white_start = positions(white.get_observation())
        # Seed goals before torque is enabled so the white arm cannot jump.
        white.bus.sync_write("Goal_Position", white_start)

        signs = {joint: (-1.0 if joint in args.invert else 1.0) for joint in JOINTS}
        print("\n启动姿态已读取。映射为相对运动，不要求两臂零位相同。")
        print("方向：" + ", ".join(f"{j}={'-' if signs[j] < 0 else '+'}" for j in JOINTS))
        print(
            f"白臂总范围：手臂关节 ±{args.max_delta_deg:.1f}°，"
            f"夹爪 ±{args.max_gripper_delta:.1f}；最长 {args.duration_s:.0f}s。"
        )
        print("先托住两条手臂并清空周围；随时按 q/ESC、Ctrl-C 或切断 12V。")
        if input("输入 FOLLOW 才给白臂上扭矩并开始：").strip() != "FOLLOW":
            print("已取消；没有启用白臂扭矩。")
            return 0

        white.bus.enable_torque()
        saved_terminal = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        started = time.monotonic()
        period = 1.0 / args.fps
        last_print = 0.0
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            if key_available():
                print("\n收到停止键。")
                break

            black_now = positions(black.get_observation())
            target = bounded_relative_targets(
                black_now,
                black_start,
                white_start,
                signs,
                args.max_delta_deg,
                args.max_gripper_delta,
            )
            sent = white.send_action(target)
            white_now = positions(white.get_observation())
            arm_errors = {
                joint: abs(float(sent[f"{joint}.pos"]) - white_now[joint])
                for joint in JOINTS
                if joint != "gripper"
            }
            worst_joint = max(arm_errors, key=arm_errors.get)
            if arm_errors[worst_joint] > args.tracking_error_deg:
                raise RuntimeError(
                    f"tracking error {arm_errors[worst_joint]:.1f}° on {worst_joint} "
                    f"> {args.tracking_error_deg:.1f}°"
                )

            elapsed = time.monotonic() - started
            if elapsed - last_print >= 0.5:
                delta_text = " ".join(
                    f"{joint}={float(sent[f'{joint}.pos']) - white_start[joint]:+.1f}"
                    for joint in JOINTS
                )
                print(f"\r{elapsed:5.1f}s white delta: {delta_text}", end="", flush=True)
                last_print = elapsed

            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
        print("\n测试结束；正在松开白臂扭矩。")
        return 0
    except KeyboardInterrupt:
        print("\nCtrl-C：停止并松扭矩。")
        return 130
    finally:
        if saved_terminal is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_terminal)
        if white_connected:
            white.disconnect()
        if black_connected:
            black.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
