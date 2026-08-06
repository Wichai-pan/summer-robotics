#!/usr/bin/env python3
"""Supervised replay of the recorded black-arm face-cream grasp.

This is a fixed-scene baseline, not a general grasp policy.  It reuses the
legacy ``arm_keyboard.py`` P-control coordinate convention because the four
waypoints were recorded with that controller on 2026-08-05.

Every motion phase needs a separate ``MOVE`` confirmation. Keep the base,
Gemini angle, desk position, and face-cream position fixed for this test.
"""

from __future__ import annotations

import argparse
import time

from arm_keyboard import apply_joint_calibration
from portutil import BOARDS, PortResolutionError, resolve_port


ZERO = {
    "shoulder_pan": 0.0, "shoulder_lift": 0.0, "elbow_flex": 0.0,
    "wrist_flex": 0.0, "wrist_roll": 0.0, "gripper": 0.0,
}

# Captured through tools/arm_keyboard.py black on 2026-08-05.
GRASP_STAGES = [
    ("pregrasp_open", {
        "elbow_flex": -146.0, "gripper": 60.0, "shoulder_lift": -2.0,
        "shoulder_pan": 16.0, "wrist_flex": 56.0, "wrist_roll": 270.0,
    }),
    ("descend_open", {
        "elbow_flex": -152.0, "gripper": 60.0, "shoulder_lift": -2.0,
        "shoulder_pan": 16.0, "wrist_flex": 56.0, "wrist_roll": 270.0,
    }),
    ("close_gripper", {
        "elbow_flex": -152.0, "gripper": 10.0, "shoulder_lift": -2.0,
        "shoulder_pan": 16.0, "wrist_flex": 56.0, "wrist_roll": 270.0,
    }),
    ("lift", {
        "elbow_flex": -70.0, "gripper": 10.0, "shoulder_lift": -2.0,
        "shoulder_pan": 16.0, "wrist_flex": 57.0, "wrist_roll": 270.0,
    }),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-seconds", type=float, default=4.0,
                        help="interpolation duration for each phase (default: 4.0)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the recorded phases without opening the motor port")
    return parser.parse_args()


def p_control_step(robot, controller_target: dict[str, float], kp: float = 0.5) -> None:
    """Send exactly the same calibrated P-control convention as arm_keyboard.py."""
    observation = robot.get_observation()
    action = {}
    for joint, target in controller_target.items():
        raw = observation[f"{joint}.pos"]
        current = apply_joint_calibration(joint, raw)
        action[f"{joint}.pos"] = current + kp * (target - current)
    robot.send_action(action)


def read_measured_pose(robot) -> dict[str, float]:
    observation = robot.get_observation()
    return {
        key.removesuffix(".pos"): round(float(value), 2)
        for key, value in observation.items()
        if key.endswith(".pos")
    }


def move_phase(robot, previous: dict[str, float], target: dict[str, float], duration: float) -> None:
    """Linearly interpolate controller targets and hold briefly at the endpoint."""
    started = time.monotonic()
    while True:
        alpha = min(1.0, (time.monotonic() - started) / duration)
        intermediate = {
            joint: previous[joint] + alpha * (target[joint] - previous[joint])
            for joint in target
        }
        p_control_step(robot, intermediate)
        if alpha >= 1.0:
            break
        time.sleep(0.02)
    for _ in range(25):  # 0.5 s endpoint hold
        p_control_step(robot, target)
        time.sleep(0.02)


def confirm(label: str) -> bool:
    reply = input(
        f"\n下一阶段 {label}。确认路径清空、手和线材远离机械臂、可立即断开黑臂 12V？"
        "输入 MOVE 执行，其他任何输入取消： "
    )
    return reply.strip() == "MOVE"


def run_sequence(robot, stages: list[tuple[str, dict[str, float]]], previous: dict[str, float], duration: float) -> tuple[bool, dict[str, float]]:
    for label, target in stages:
        if not confirm(label):
            print("已取消；未执行后续阶段。")
            return False, previous
        print(f"低速执行 {label}（约 {duration:.1f} 秒）…")
        move_phase(robot, previous, target, duration)
        previous = target
        print(f"{label} 完成；实测关节：{read_measured_pose(robot)}")
    return True, previous


def main() -> int:
    args = parse_args()
    if args.stage_seconds <= 0:
        raise SystemExit("--stage-seconds 必须为正数。")
    if args.dry_run:
        for name, pose in GRASP_STAGES:
            print(f"{name}: {pose}")
        return 0

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    try:
        port = resolve_port(BOARDS["black"])
    except PortResolutionError as exc:
        print(exc)
        return 2

    print("固定面霜抓取回放：黑臂 only；不控制底盘、白臂或云台。")
    print(f"黑臂端口：{port}")
    if input("确认场景与录制时一致，输入 REPLAY 继续： ").strip() != "REPLAY":
        print("已取消；未打开电机串口。")
        return 0

    robot = SO100Follower(SO100FollowerConfig(port=port, id="black_arm"))
    try:
        # Do not enter a new calibration flow; use the existing black_arm file.
        robot.connect(calibrate=False)
        print(f"连接完成；当前实测：{read_measured_pose(robot)}")
        if not confirm("home_zero（已验证的原键盘脚本同一归零动作）"):
            return 0
        move_phase(robot, ZERO, ZERO, 3.0)
        print(f"归零完成；实测关节：{read_measured_pose(robot)}")

        completed, current = run_sequence(robot, GRASP_STAGES, ZERO, args.stage_seconds)
        if not completed:
            return 0

        print("\n已到 lift，夹爪仍保持合拢。此时可拍摄结果。")
        if input("输入 RETURN 执行受监督放回；其他输入保持当前姿态，直到手动断开/中断： ").strip() == "RETURN":
            down_closed = GRASP_STAGES[1][1].copy()
            down_closed["gripper"] = GRASP_STAGES[2][1]["gripper"]
            return_stages = [
                ("lower_with_object", down_closed),
                ("release", GRASP_STAGES[1][1]),
                ("retreat_open", GRASP_STAGES[0][1]),
                ("home_zero", ZERO),
            ]
            run_sequence(robot, return_stages, current, args.stage_seconds)
    except KeyboardInterrupt:
        print("\n已中断。")
    finally:
        if robot.is_connected:
            robot.disconnect()
        print("黑臂已松扭矩、端口已关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
