"""连续监控总线上舵机的在线状态，用来揪出松动的接头。

一边【轻轻拨动手臂的不同段 / 各个舵机接头】，一边看屏幕：谁一动就掉线，
松的接头就在那附近。只读(ping)，不会让臂动。

用法:  python tools/bus_monitor.py [white|black]   (默认 white)
退出:  Ctrl-C
"""
import os
import sys
import time
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

# 跨平台端口解析（Mac/Windows/Linux 通用，与其它脚本共用）
from portutil import BOARDS, resolve_port, PortResolutionError

IDS = list(range(1, 10))   # 1..9（白板：臂1-6 + 轮7-9）


def main():
    arm = sys.argv[1].lower() if len(sys.argv) > 1 else "white"
    if arm not in BOARDS:
        raise SystemExit("用法: python tools/bus_monitor.py [white|black] [可选端口]")
    override = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("XLEROBOT_PORT")
    try:
        port = resolve_port(BOARDS[arm], override=override)
    except PortResolutionError as e:
        raise SystemExit(str(e))
    print(f"监控 {arm} 板: {port}   (Ctrl-C 退出)")
    print("一边轻拨手臂各段/接头，一边看谁掉线（掉线会单独报一行）\n")

    ph = PortHandler(port)
    if not ph.openPort():
        raise SystemExit("打不开端口（可能被 arm_keyboard 占用，先关掉它）")
    ph.setBaudRate(1_000_000)
    pk = PacketHandler(0)

    state = {i: None for i in IDS}
    try:
        while True:
            cells = []
            for i in IDS:
                _, comm, _ = pk.ping(ph, i)
                ok = comm == COMM_SUCCESS
                if state[i] is not None and state[i] != ok:
                    stamp = time.strftime("%H:%M:%S")
                    msg = "恢复 ✓" if ok else "掉线 ✗  <<< 松的在这附近"
                    print(f"\n[{stamp}] ID {i} {msg}")
                state[i] = ok
                cells.append(f"{i}{'✓' if ok else '✗'}")
            print("\r在线: " + "  ".join(cells) + "   ", end="", flush=True)
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n退出")
    finally:
        ph.closePort()


if __name__ == "__main__":
    main()
