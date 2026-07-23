#!/usr/bin/env python3
"""独立、小幅测试黑板上的深度相机云台电机 ID 7、8。

这不是整机遥操作：不连接或命令任何机械臂关节/底盘。每次终端输入只会让
一个云台轴相对当前位置移动约 5°，用于判断「整机键盘映射」还是「云台电机」
的问题。运行前必须退出 ``4_xlerobot_teleop_keyboard.py``，以释放黑板串口。

按键（输入后按 Enter）：
    a / d  : ID 7 小幅负向 / 正向
    j / l  : ID 8 小幅负向 / 正向
    q      : 停止并松扭矩后退出
"""

import os
import sys
import time

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler

from portutil import BOARDS, PortResolutionError, resolve_port


GIMBAL = {7: "云台轴 7", 8: "云台轴 8"}
BAUD = 1_000_000

# STS3215 control table
OP_MODE = 33
TORQUE = 40
GOAL_POSITION = 42
PRESENT_POSITION = 56
MODE_POSITION = 0
STEP_TICKS = 60  # 4096 ticks / 360°，约 5.3°


def read_position(packet: PacketHandler, port: PortHandler, motor_id: int) -> int | None:
    value, comm, _ = packet.read2ByteTxRx(port, motor_id, PRESENT_POSITION)
    return value if comm == COMM_SUCCESS else None


def main() -> None:
    override = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("XLEROBOT_PORT")
    try:
        device = resolve_port(BOARDS["black"], override=override)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    port = PortHandler(device)
    if not port.openPort():
        raise SystemExit(f"打不开黑板端口：{device}。先退出整机遥操作程序。")
    port.setBaudRate(BAUD)
    packet = PacketHandler(0)

    online: list[int] = []
    try:
        print(f"黑板端口：{device}")
        print("\n[只读检查]")
        for motor_id, name in GIMBAL.items():
            _, comm, _ = packet.ping(port, motor_id)
            if comm != COMM_SUCCESS:
                print(f"  ✗ ID {motor_id}（{name}）无响应")
                continue
            mode, comm, _ = packet.read1ByteTxRx(port, motor_id, OP_MODE)
            pos = read_position(packet, port, motor_id)
            print(f"  ✓ ID {motor_id}（{name}） mode={mode}  position={pos}")
            if mode != MODE_POSITION:
                print("    未处于位置模式；为避免意外改变模式，本测试不会命令该轴。")
                continue
            online.append(motor_id)

        if not online:
            raise SystemExit("没有处于位置模式的云台轴可测试。检查 12V、总线或先完成整机标定。")

        answer = input("\n云台周围已清空？输入 yes 开始小幅测试：").strip().lower()
        if answer != "yes":
            print("已取消。")
            return

        for motor_id in online:
            packet.write1ByteTxRx(port, motor_id, TORQUE, 1)

        commands = {"a": (7, -1), "d": (7, 1), "j": (8, -1), "l": (8, 1)}
        print("\na/d 控制 ID 7；j/l 控制 ID 8；q 退出。每次约 5°。")
        while True:
            key = input("> ").strip().lower()
            if key in {"q", "quit", "exit"}:
                break
            if key not in commands:
                print("请输入 a、d、j、l 或 q。")
                continue
            motor_id, direction = commands[key]
            if motor_id not in online:
                print(f"ID {motor_id} 不可用。")
                continue
            current = read_position(packet, port, motor_id)
            if current is None:
                print(f"无法读取 ID {motor_id} 的当前位置，跳过。")
                continue
            target = max(0, min(4095, current + direction * STEP_TICKS))
            # scservo_sdk 的写入 API 返回 (communication_result, servo_error)，
            # 与 read2ByteTxRx 的三元返回值不同。
            comm, _ = packet.write2ByteTxRx(port, motor_id, GOAL_POSITION, target)
            if comm != COMM_SUCCESS:
                print(f"发送 ID {motor_id} 失败（通信码 {comm}）。")
                continue
            time.sleep(0.35)
            after = read_position(packet, port, motor_id)
            print(f"ID {motor_id}: {current} → 目标 {target} → 当前 {after}")
    finally:
        for motor_id in GIMBAL:
            packet.write1ByteTxRx(port, motor_id, TORQUE, 0)
        port.closePort()
        print("云台已松扭矩、端口已关闭。")


if __name__ == "__main__":
    main()
