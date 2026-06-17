"""键盘控制 LeKiwi 底盘（3 个全向轮）。手感同机械臂键盘控制。

⚠️ 第一次务必把机器人垫高、3 个轮子离地！确认能转、方向对了，再放地上慢开。
⚠️ 轮子在【白板】(臂+底盘那块)总线上：先接好白板(12V + USB)。
⚠️ macOS 首次需在 系统设置>隐私与安全性>输入监控 给终端授权。

按键： W/S 前后   A/D 左右平移   Q/E 左右旋转   空格 急停   ESC 或 X 退出
用法： python tools/base_keyboard.py
"""
import glob
import time
import numpy as np
from pynput import keyboard
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

WHITE_SERIAL = "5B3D040988"                  # 白板：臂 1-6 + 底盘轮 7-9
WHEEL_IDS = [7, 8, 9]                         # 左轮 / 后轮 / 右轮（顺序对应运动学输出）
XY_SPEED = 0.12                              # m/s（保守）
THETA_SPEED = 40.0                          # deg/s
LOOP_HZ = 30

# STS3215 寄存器
OP_MODE, TORQUE, GOAL_VEL, LOCK = 33, 40, 46, 55
MODE_VELOCITY = 1
SIGN_BIT = 15


def find_port(serial):
    m = sorted(glob.glob(f"/dev/cu.usbmodem{serial}*"))
    if not m:
        raise SystemExit(f"找不到白板端口(序列号 {serial})。确认白板已接 USB + 12V。")
    return m[0]


def encode_sm(value):
    """符号-幅值编码（与 lerobot 一致，sign bit=15）。"""
    mag = min(abs(int(value)), (1 << SIGN_BIT) - 1)
    return ((1 << SIGN_BIT) | mag) if value < 0 else mag


def body_to_wheel_raw(x, y, theta, wheel_radius=0.05, base_radius=0.125, max_raw=3000):
    """机体速度(x m/s, y m/s, theta deg/s) -> 3 个轮子的原始速度（复刻 lerobot LeKiwi）。"""
    vel = np.array([x, y, theta * np.pi / 180.0])
    angles = np.radians(np.array([240, 0, 120]) - 90)
    m = np.array([[np.cos(a), np.sin(a), base_radius] for a in angles])
    degps = (m.dot(vel) / wheel_radius) * (180.0 / np.pi)
    steps_per_deg = 4096.0 / 360.0
    raw_floats = [abs(d) * steps_per_deg for d in degps]
    mx = max(raw_floats) if raw_floats else 0.0
    if mx > max_raw:
        degps = degps * (max_raw / mx)
    return [int(round(d * steps_per_deg)) for d in degps]


def main():
    port = find_port(WHITE_SERIAL)
    print(f"白板端口: {port}")
    ph = PortHandler(port)
    if not ph.openPort():
        raise SystemExit("打不开端口")
    ph.setBaudRate(1_000_000)
    pk = PacketHandler(0)

    # 确认轮子在线
    for wid in WHEEL_IDS:
        _, comm, _ = pk.ping(ph, wid)
        if comm != COMM_SUCCESS:
            raise SystemExit(f"轮子 ID {wid} 没响应 —— 检查白板供电/连接。")

    ans = input("⚠️  机器人已垫高、3 个轮子完全离地了吗？输入 yes 继续: ").strip().lower()
    if ans != "yes":
        print("已取消。先垫高让轮子离地。")
        ph.closePort()
        return

    # 速度模式 + 上扭矩
    for wid in WHEEL_IDS:
        mode, _, _ = pk.read1ByteTxRx(ph, wid, OP_MODE)
        if mode != MODE_VELOCITY:
            pk.write1ByteTxRx(ph, wid, LOCK, 0)
            pk.write1ByteTxRx(ph, wid, OP_MODE, MODE_VELOCITY)
            pk.write1ByteTxRx(ph, wid, LOCK, 1)
        pk.write1ByteTxRx(ph, wid, TORQUE, 1)

    pressed = set()

    def on_press(key):
        try:
            pressed.add(key.char.lower())
        except AttributeError:
            if key == keyboard.Key.esc:
                pressed.add("esc")
            elif key == keyboard.Key.space:
                pressed.add("space")

    def on_release(key):
        try:
            pressed.discard(key.char.lower())
        except AttributeError:
            if key == keyboard.Key.esc:
                pressed.discard("esc")
            elif key == keyboard.Key.space:
                pressed.discard("space")

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    print("\n开动！ W/S 前后  A/D 左右平移  Q/E 旋转  空格 急停  ESC/X 退出\n")
    period = 1.0 / LOOP_HZ
    try:
        while True:
            if "esc" in pressed or "x" in pressed:
                break
            if "space" in pressed:
                x = y = theta = 0.0
            else:
                x = (XY_SPEED if "w" in pressed else 0) - (XY_SPEED if "s" in pressed else 0)
                y = (XY_SPEED if "a" in pressed else 0) - (XY_SPEED if "d" in pressed else 0)
                theta = (THETA_SPEED if "q" in pressed else 0) - (THETA_SPEED if "e" in pressed else 0)
            raw = body_to_wheel_raw(x, y, theta)
            for wid, r in zip(WHEEL_IDS, raw):
                pk.write2ByteTxRx(ph, wid, GOAL_VEL, encode_sm(r))
            time.sleep(period)
    finally:
        listener.stop()
        for wid in WHEEL_IDS:                    # 兜底停转 + 松扭矩
            pk.write2ByteTxRx(ph, wid, GOAL_VEL, 0)
            pk.write1ByteTxRx(ph, wid, TORQUE, 0)
        ph.closePort()
        print("已停车、退出。")


if __name__ == "__main__":
    main()
