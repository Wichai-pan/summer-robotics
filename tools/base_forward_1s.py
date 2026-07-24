#!/usr/bin/env python3
"""按键盘 W 的同一映射让 XLeRobot 底盘直行 1 秒，然后自动停止。

这是独立的真机底盘测试，不调用 Gemini，也不控制机械臂。
运行前：地面清空、机器人前方至少留 2 米、双臂收好、旁边有人可断电。
"""

from __future__ import annotations

import os
import sys
import time

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler

from portutil import BOARDS, PortResolutionError, resolve_port
from base_keyboard import WHEEL_IDS, XY_SPEED, body_to_wheel_raw, encode_sm


# 复用 base_keyboard.py 中已经验证的底盘运动学与默认前进速度，
# 不再直接猜三个轮子的速度正负号。
DURATION_SECONDS = 1.0

# STS3215 register addresses / velocity operating mode.
OP_MODE, TORQUE, GOAL_VEL, LOCK = 33, 40, 46, 55
MODE_VELOCITY = 1


def main() -> int:
    override = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("XLEROBOT_PORT")
    try:
        port = resolve_port(BOARDS["white"], override=override)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"白板（底盘）端口：{port}")
    print(
        f"测试：按 base_keyboard.py 的 W 键默认前进速度 "
        f"({XY_SPEED:.2f} m/s) 直行 {DURATION_SECONDS:.1f} 秒。"
    )
    print("不会控制 ID 1–6 的白臂。ID 7/8/9 仅在测试期间上扭矩。")

    port_handler = PortHandler(port)
    if not port_handler.openPort():
        raise SystemExit("无法打开白板串口。确认 USB 和 12V 供电。")
    port_handler.setBaudRate(1_000_000)
    packet = PacketHandler(0)

    try:
        missing = []
        for motor_id in WHEEL_IDS:
            _, comm_result, _ = packet.ping(port_handler, motor_id)
            if comm_result != COMM_SUCCESS:
                missing.append(motor_id)
        if missing:
            raise SystemExit(f"底盘电机 {missing} 没有响应；为安全起见取消。")

        confirmation = input(
            "确认前方清空、双臂不会碰撞且可以立即断电？输入 MOVE 才会移动： "
        ).strip()
        if confirmation != "MOVE":
            print("已取消，没有发送运动指令。")
            return 0

        for motor_id in WHEEL_IDS:
            mode, _, _ = packet.read1ByteTxRx(port_handler, motor_id, OP_MODE)
            if mode != MODE_VELOCITY:
                packet.write1ByteTxRx(port_handler, motor_id, LOCK, 0)
                packet.write1ByteTxRx(port_handler, motor_id, OP_MODE, MODE_VELOCITY)
                packet.write1ByteTxRx(port_handler, motor_id, LOCK, 1)
            packet.write1ByteTxRx(port_handler, motor_id, TORQUE, 1)

        raw = body_to_wheel_raw(x=XY_SPEED, y=0.0, theta=0.0)
        print(f"开始直行…（复用键盘 W 的轮速映射：{dict(zip(WHEEL_IDS, raw))}）")
        for motor_id, velocity in zip(WHEEL_IDS, raw):
            packet.write2ByteTxRx(port_handler, motor_id, GOAL_VEL, encode_sm(velocity))
        time.sleep(DURATION_SECONDS)
        print("1 秒到，发送停止指令。")
        return 0
    finally:
        # 无论 Ctrl-C、通信异常或正常结束，均先停止再松底盘扭矩。
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
