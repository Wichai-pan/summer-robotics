#!/usr/bin/env python3
"""XLeRobot 底盘的固定、安全单步动作。

动作严格复用 ``base_keyboard.py`` 的运动学与默认速度：
  forward_1s       键盘 W 的前进，1 秒
  forward_small    键盘 W 的前进，0.3 秒（约 3.6 cm）
  turn_left_small  键盘 Q 的左转，约 16°
  turn_right_small 键盘 E 的右转，约 16°

每次只执行一个固定动作，结束后必定写零速度并松开底盘扭矩。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler

from base_keyboard import THETA_SPEED, WHEEL_IDS, XY_SPEED, body_to_wheel_raw, encode_sm
from portutil import BOARDS, PortResolutionError, resolve_port


OP_MODE, TORQUE, GOAL_VEL, LOCK = 33, 40, 46, 55
MODE_VELOCITY = 1

# THETA_SPEED is 40 deg/s in base_keyboard.py; 0.4 s gives approximately 16°.
MOTIONS = {
    "forward_1s": (XY_SPEED, 0.0, 0.0, 1.0, "键盘 W 前进 1 秒"),
    "forward_small": (XY_SPEED, 0.0, 0.0, 0.3, "键盘 W 小步前进约 3.6 cm"),
    "turn_left_small": (0.0, 0.0, THETA_SPEED, 0.4, "键盘 Q 左转约 16°"),
    "turn_right_small": (0.0, 0.0, -THETA_SPEED, 0.4, "键盘 E 右转约 16°"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(MOTIONS), help="一次要执行的固定动作")
    parser.add_argument("port", nargs="?", help="可选：手动覆盖白板端口")
    args = parser.parse_args()

    x, y, theta, duration, label = MOTIONS[args.action]
    override = args.port or os.environ.get("XLEROBOT_PORT")
    try:
        port = resolve_port(BOARDS["white"], override=override)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    raw = body_to_wheel_raw(x=x, y=y, theta=theta)
    print(f"白板（底盘）端口：{port}")
    print(f"单步动作：{args.action} — {label}")
    print(f"轮速（复用 base_keyboard.py）：{dict(zip(WHEEL_IDS, raw))}")
    print("只会操作白板 ID 7/8/9；动作结束会停止并松扭矩。")

    port_handler = PortHandler(port)
    if not port_handler.openPort():
        raise SystemExit("无法打开白板串口。确认 USB 与 12V 供电。")
    port_handler.setBaudRate(1_000_000)
    packet = PacketHandler(0)

    try:
        missing = []
        for motor_id in WHEEL_IDS:
            _, comm_result, _ = packet.ping(port_handler, motor_id)
            if comm_result != COMM_SUCCESS:
                missing.append(motor_id)
        if missing:
            raise SystemExit(f"底盘电机 {missing} 没有响应；取消动作。")

        answer = input(
            "确认周围清空、双臂不会碰撞且可立即断开 12V？输入 MOVE 执行： "
        ).strip()
        if answer != "MOVE":
            print("已取消，没有发送动作。")
            return 2

        for motor_id in WHEEL_IDS:
            mode, _, _ = packet.read1ByteTxRx(port_handler, motor_id, OP_MODE)
            if mode != MODE_VELOCITY:
                packet.write1ByteTxRx(port_handler, motor_id, LOCK, 0)
                packet.write1ByteTxRx(port_handler, motor_id, OP_MODE, MODE_VELOCITY)
                packet.write1ByteTxRx(port_handler, motor_id, LOCK, 1)
            packet.write1ByteTxRx(port_handler, motor_id, TORQUE, 1)

        print(f"执行 {label}…")
        for motor_id, velocity in zip(WHEEL_IDS, raw):
            packet.write2ByteTxRx(port_handler, motor_id, GOAL_VEL, encode_sm(velocity))
        time.sleep(duration)
        print("动作结束，发送停止指令。")
        return 0
    finally:
        for motor_id in WHEEL_IDS:
            try:
                packet.write2ByteTxRx(port_handler, motor_id, GOAL_VEL, 0)
                packet.write1ByteTxRx(port_handler, motor_id, TORQUE, 0)
            except Exception:
                pass
        port_handler.closePort()
        print("底盘已停止并松扭矩，端口已关闭。")


if __name__ == "__main__":
    raise SystemExit(main())
