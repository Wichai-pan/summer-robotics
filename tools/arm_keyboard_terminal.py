#!/usr/bin/env python3
"""SSH-terminal keyboard control for one SO100/SO101 arm.

This keeps the joint mapping and P controller used by ``arm_keyboard.py`` but
does not depend on pynput or a graphical DISPLAY.  Unlike the legacy script,
it starts from the measured pose and never moves the arm to zero on startup.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import tty

from arm_keyboard import apply_joint_calibration, p_control_loop
from portutil import BOARDS, PortResolutionError, resolve_port


class TerminalKeyboard:
    """Expose one terminal character at a time in KeyboardTeleop's format."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._saved_attributes: list | None = None

    def connect(self) -> None:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "stdin 不是交互式终端；请用 scripts/jetson_robot_exec.sh --interactive 运行"
            )
        self._fd = sys.stdin.fileno()
        self._saved_attributes = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

    def get_action(self) -> dict[str, bool]:
        if self._fd is None:
            return {}
        readable, _, _ = select.select([self._fd], [], [], 0)
        if not readable:
            return {}
        key = os.read(self._fd, 1).decode("utf-8", errors="ignore").lower()
        return {key: True} if key else {}

    def disconnect(self) -> None:
        if self._fd is not None and self._saved_attributes is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved_attributes)
        self._fd = None
        self._saved_attributes = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 SSH 终端控制 SO100/SO101；启动时保持当前姿态，不自动归零。"
    )
    parser.add_argument("arm", choices=sorted(BOARDS), help="要控制的机械臂")
    parser.add_argument(
        "port",
        nargs="?",
        default=None,
        help="可选串口覆盖；通常按控制板 USB 序列号自动识别",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    override = args.port or os.environ.get("XLEROBOT_PORT")
    try:
        port = resolve_port(BOARDS[args.arm], override=override)
    except PortResolutionError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"将控制 {args.arm} 臂；串口：{port}")
    print("启动后不会归零；目标从当前实测姿态开始。")
    print("请清空机械臂运动范围，并确保可以立即切断 12V 电源。")
    if input(f"输入 {args.arm.upper()} 才连接并给该臂上扭矩： ").strip() != args.arm.upper():
        print("已取消；没有打开串口。")
        return 1

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    robot = SO100Follower(SO100FollowerConfig(port=port, id=f"{args.arm}_arm"))
    keyboard = TerminalKeyboard()
    robot_connected = False
    keyboard_connected = False
    try:
        robot.connect()
        robot_connected = True

        observation = robot.get_observation()
        start_positions = {
            key.removesuffix(".pos"): float(value)
            for key, value in observation.items()
            if key.endswith(".pos")
        }
        # Match the legacy controller's internal target coordinate system so
        # existing saved poses and the familiar key directions remain valid.
        target_positions = {
            joint: apply_joint_calibration(joint, value)
            for joint, value in start_positions.items()
        }

        keyboard.connect()
        keyboard_connected = True
        print("\n按键与原 arm_keyboard.py 一致：")
        print("Q/A 肩 pan | W/S 肩 lift | E/D 肘 | R/F 腕 flex")
        print("T/G 腕 roll | Y/H 夹爪 | P 打印姿态 | X 回到启动姿态并退出")
        print("每次关节 1°，夹爪 5%；请一次只按一个键并观察运动。\n")
        p_control_loop(
            robot,
            keyboard,
            target_positions,
            start_positions,
            kp=0.5,
            control_freq=50,
        )
        return 0
    except KeyboardInterrupt:
        print("\n收到 Ctrl-C；立即松扭矩退出，不执行回位。")
        return 130
    finally:
        if keyboard_connected:
            keyboard.disconnect()
        if robot_connected:
            robot.disconnect()
            print("机械臂已松扭矩，串口已关闭。")


if __name__ == "__main__":
    raise SystemExit(main())
