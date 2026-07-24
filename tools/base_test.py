"""底盘轮子安全测试：逐个轮子(ID 7/8/9)轻转 1 秒，肉眼确认电机能动。

⚠️ 跑之前必须把机器人垫高、3 个轮子完全离地！否则机器人会在地上乱跑。
⚠️ 轮子在【白板】(臂+底盘那块)的总线上，先把白板接好(12V + USB)。

用法：  python tools/base_test.py
"""
import os
import sys
import time
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

# 跨平台端口解析（Mac/Windows/Linux 通用）
from portutil import BOARDS, resolve_port, PortResolutionError

WHITE_SERIAL = BOARDS["white"]       # 白板(arm1)：臂 1-6 + 底盘轮 7-9
WHEELS = {7: "左轮", 8: "后轮", 9: "右轮"}
SPEED = 300                          # 轻速(STS3215 满速约 3400)，保守
SPIN_SEC = 1.0

# STS3215 寄存器
OP_MODE, TORQUE, GOAL_VEL, LOCK = 33, 40, 46, 55
MODE_VELOCITY = 1


def main():
    # 端口自动按板序列号解析；也可命令行参数 / 环境变量 XLEROBOT_PORT 手动指定
    override = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("XLEROBOT_PORT")
    try:
        port = resolve_port(WHITE_SERIAL, override=override)
    except PortResolutionError as e:
        raise SystemExit(str(e))
    print(f"白板端口: {port}")
    ph = PortHandler(port)
    if not ph.openPort():
        raise SystemExit("打不开端口")
    ph.setBaudRate(1_000_000)
    pk = PacketHandler(0)

    # [1] 只读：确认 3 个轮子在线 + 当前模式
    print("\n[1/3] 检查轮子在线 & 当前模式：")
    online = []
    for wid, name in WHEELS.items():
        _, comm, _ = pk.ping(ph, wid)
        if comm != COMM_SUCCESS:
            print(f"  ✗ ID {wid} ({name}) 没响应")
            continue
        mode, _, _ = pk.read1ByteTxRx(ph, wid, OP_MODE)
        print(f"  ✓ ID {wid} ({name})  当前模式={mode}({'速度' if mode == MODE_VELOCITY else '位置'})")
        online.append(wid)
    if not online:
        raise SystemExit("没有轮子响应 —— 检查白板供电(12V)/USB。")

    # 安全闸：必须确认离地
    ans = input("\n⚠️  机器人是否已垫高、3 个轮子完全离地？输入 yes 继续，其它退出: ").strip().lower()
    if ans != "yes":
        print("已取消。把机器人垫起来让轮子离地，再重跑。")
        ph.closePort()
        return

    # [2] 确保速度模式 + 上扭矩
    print("\n[2/3] 设为速度模式、上扭矩…")
    for wid in online:
        mode, _, _ = pk.read1ByteTxRx(ph, wid, OP_MODE)
        if mode != MODE_VELOCITY:
            pk.write1ByteTxRx(ph, wid, LOCK, 0)            # 解锁 EEPROM
            pk.write1ByteTxRx(ph, wid, OP_MODE, MODE_VELOCITY)
            pk.write1ByteTxRx(ph, wid, LOCK, 1)            # 重新锁
        pk.write1ByteTxRx(ph, wid, TORQUE, 1)

    # [3] 逐个轻转
    print("\n[3/3] 逐个轮子轻转 1 秒（看哪个在转）：")
    try:
        for wid in online:
            print(f"  → ID {wid} ({WHEELS[wid]}) 转…")
            pk.write2ByteTxRx(ph, wid, GOAL_VEL, SPEED)
            time.sleep(SPIN_SEC)
            pk.write2ByteTxRx(ph, wid, GOAL_VEL, 0)
            time.sleep(0.5)
    finally:
        for wid in online:                                # 兜底：全部停转 + 松扭矩
            pk.write2ByteTxRx(ph, wid, GOAL_VEL, 0)
            pk.write1ByteTxRx(ph, wid, TORQUE, 0)
        ph.closePort()
    print("\n完成。每个轮子都转了 = 底盘电机 OK ✅")


if __name__ == "__main__":
    main()
