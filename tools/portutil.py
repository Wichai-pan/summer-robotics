#!/usr/bin/env python3
"""跨平台串口解析：按板子的 USB 序列号自动找当前端口。Mac / Windows / Linux 通用。

机器人控制板用 WCH CH343 芯片(VID 0x1A86)，每块板有出厂唯一序列号(如 5B3D040988)。
端口名各平台不同、且换 USB 口会变：
  - Windows : COMx                              (序列号在 pyserial 的 serial_number / hwid)
  - macOS   : /dev/cu.usbmodem<序列号><接口号>   (序列号嵌在设备路径里)
  - Linux   : /dev/ttyACM* / /dev/ttyUSB*       (序列号在 serial_number / hwid)

⚠️ 选错端口 = 控制错的机械臂(安全问题)。所以匹配到多个时直接报错，绝不瞎猜。

诊断(看本机现在有哪些串口、能不能认出白/黑板)：
    python tools/portutil.py
"""
import os
import sys
import glob
import collections

try:
    import serial.tools.list_ports as list_ports
except ImportError as e:  # pyserial 随 lerobot / scservo_sdk 一起装
    raise ImportError(
        "需要 pyserial（随 lerobot / scservo_sdk 一起装；或 `pip install pyserial`）。"
    ) from e


# 板子注册表：名字 -> USB 序列号（板子固定，端口名会变）
BOARDS = {
    "white": "5B3D040988",   # arm 1 · 白臂(关节 1-6) + 底盘轮 7-9
    "black": "5B3D043224",   # arm 2 · 黑臂(关节 1-6) + 辅助 7-8
}

WCH_VID = 0x1A86             # CH343 / CH34x 厂商 ID


class PortResolutionError(RuntimeError):
    """找不到端口、或匹配到多个无法确定时抛出。"""


_Port = collections.namedtuple("_Port", "device serial hwid vid pid desc")


def _norm(s):
    # CH343 序列号是 16 进制风格字符串：Windows 全大写、macOS 可能小写 -> 统一 casefold
    return (s or "").strip().casefold()


def _from_info(p):
    return _Port(p.device, p.serial_number, p.hwid, p.vid, p.pid, p.description)


def _enumerate(board_serial):
    """列出候选端口：comports() 全平台通用，外加 macOS 的 cu.usbmodem glob 兜底。"""
    cands = [_from_info(p) for p in list_ports.comports()]
    if sys.platform == "darwin":
        # macOS 上 serial_number/hwid 常为空(Apple Silicon 的 pyserial 回归 + CH34x 描述符问题)，
        # 但序列号嵌在 /dev/cu.usbmodem<序列号><接口> 路径里。union 进来确保设备一定在候选集中。
        seen = {c.device for c in cands}
        for path in glob.glob(f"/dev/cu.usbmodem{board_serial}*"):
            if path not in seen:
                cands.append(_Port(path, None, None, None, None, None))
    return cands


def _matches(c, target):
    """target 已 casefold。三种命中方式，任一即算匹配。"""
    # 1) serial_number 精确(Windows 可靠；Linux 多半也有)
    if c.serial and _norm(c.serial) == target:
        return True
    # 2) 序列号嵌在设备路径里(macOS)：子串匹配，因为路径末尾还带个接口号
    if target and target in _norm(os.path.basename(c.device or "")):
        return True
    # 3) hwid 里的 SER= 字段(Linux/Windows 双保险)
    if target and ("ser=" + target) in _norm(c.hwid):
        return True
    return False


def _rank(c, target):
    dev = c.device or ""
    return (
        0 if c.vid == WCH_VID else 1,                                   # 优先 WCH 设备
        0 if dev.startswith("/dev/cu.") else 1,                         # macOS 偏好 cu.
        0 if (c.serial and _norm(c.serial) == target) else 1,          # serial 精确更权威
        dev,
    )


def _table(cands):
    if not cands:
        return "  (没有检测到任何串口)\n"
    rows = []
    for c in cands:
        vidpid = f"{c.vid:04X}:{c.pid:04X}" if (c.vid is not None and c.pid is not None) else "----:----"
        rows.append(f"  {(c.device or '?'):<26} vid:pid={vidpid}  serial={c.serial or '-'}  hwid={c.hwid or '-'}")
    return "\n".join(rows) + "\n"


def _hint():
    if sys.platform.startswith("win"):
        return ("\nWindows：设备管理器 > 端口(COM 和 LPT)，拔插板子看哪个 COM 出现/消失就是它。\n"
                "没有任何 CH343 的 COM 口 → 装 WCH 驱动 CH343SER（wch-ic.com）。")
    if sys.platform == "darwin":
        return "\nmacOS：跑 `ls /dev/cu.usbmodem*`；空的话装 WCH ch34xser_macos 驱动。"
    return "\nLinux：跑 `ls /dev/ttyACM* /dev/ttyUSB*`、`dmesg | tail`；确认用户在 dialout 组。"


def resolve_port(board_serial, *, vid=WCH_VID, override=None):
    """按板序列号解析出端口字符串（Windows 返回裸 'COMx'，原样喂给 pyserial/scservo/lerobot）。

    override: 跳过自动解析、直接用这个端口（命令行或环境变量传进来时用）。
    """
    if override:
        return override

    target = _norm(board_serial)
    if not target:
        raise PortResolutionError("板序列号为空。")

    cands = _enumerate(board_serial)
    # 永不返回 /dev/tty.*（macOS 上打开它会等载波卡住）
    survivors = [c for c in cands
                 if _matches(c, target) and not (c.device or "").startswith("/dev/tty.")]

    if not survivors:
        raise PortResolutionError(
            f"找不到板序列号 {board_serial!r}（VID {vid:#06x}）对应的串口。确认板子已接 USB + 12V。\n"
            f"当前检测到的串口：\n{_table(cands)}{_hint()}"
        )

    survivors.sort(key=lambda c: _rank(c, target))
    distinct = {c.device for c in survivors}
    if len(distinct) > 1:
        # 安全优先：多个不同设备都匹配 -> 不自动选，让人手动指定端口
        raise PortResolutionError(
            f"有 {len(distinct)} 个端口都匹配序列号 {board_serial!r}，拒绝自动选择(选错=控制错臂)。\n"
            f"匹配项：\n{_table(survivors)}\n直接指定端口即可（命令行传端口，或设环境变量 XLEROBOT_PORT）。"
        )
    return survivors[0].device


def main():
    cands = [_from_info(p) for p in list_ports.comports()]
    print(f"平台: {sys.platform}    检测到 {len(cands)} 个串口：")
    print(_table(cands), end="")
    print("\n已注册的板子：")
    for name, serial in BOARDS.items():
        try:
            print(f"  {name:<6} ({serial}) -> {resolve_port(serial)}")
        except PortResolutionError:
            print(f"  {name:<6} ({serial}) -> 未找到（板子没接？或需装 WCH 驱动）")
    print("\n提示：先把板子接好(USB + 12V)再跑此诊断；想手动指定端口设 XLEROBOT_PORT。")


if __name__ == "__main__":
    main()
