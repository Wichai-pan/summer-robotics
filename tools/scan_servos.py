"""只读舵机扫描：ping 并读取当前位置，不上扭矩、不发送动作。"""

from __future__ import annotations

import sys

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler


PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem5B3D0409881"
BAUD = 1_000_000
PRESENT_POSITION_ADDR = 56  # STS3215 当前位置寄存器（2 字节）


def main() -> int:
    port = PortHandler(PORT)
    if not port.openPort():
        print("ERROR: 打不开端口", PORT)
        return 1
    port.setBaudRate(BAUD)
    packet = PacketHandler(0)  # protocol_end=0 → STS/SMS 系列

    found = []
    try:
        for servo_id in range(1, 21):
            model, comm, _ = packet.ping(port, servo_id)
            if comm != COMM_SUCCESS:
                continue
            position, read_comm, _ = packet.read2ByteTxRx(
                port, servo_id, PRESENT_POSITION_ADDR
            )
            if read_comm != COMM_SUCCESS:
                position = None
            found.append(servo_id)
            print(
                f"  ID {servo_id:2d}  model={model}  "
                f"当前位置(0-4095)={position}"
            )
    finally:
        port.closePort()

    print(f"\n共发现 {len(found)} 个舵机: ids={found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
