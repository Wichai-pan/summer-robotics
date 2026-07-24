"""只读舵机扫描：ping + 读当前位置，不上扭矩、不发动作（不会让臂动）。"""
import sys
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem5B3D0409881"
BAUD = 1_000_000
PRESENT_POSITION_ADDR = 56  # STS3215 当前位置寄存器（2 字节）

port = PortHandler(PORT)
if not port.openPort():
    print("ERROR: 打不开端口", PORT); sys.exit(1)
port.setBaudRate(BAUD)
packet = PacketHandler(0)  # protocol_end=0 → STS/SMS 系列

found = []
for sid in range(1, 21):
    model, comm, err = packet.ping(port, sid)
    if comm == COMM_SUCCESS:
        pos, comm2, _ = packet.read2ByteTxRx(port, sid, PRESENT_POSITION_ADDR)
        pos = pos if comm2 == COMM_SUCCESS else None
        found.append(sid)
        print(f"  ID {sid:2d}  model={model}  当前位置(0-4095)={pos}")

port.closePort()
print(f"\n共发现 {len(found)} 个舵机: ids={found}")
