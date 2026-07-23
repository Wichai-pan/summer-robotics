#!/usr/bin/env python3
"""在 macOS 上运行 XLeRobot 官方双臂键盘末端控制示例。

官方 ``2_dual_so100_keyboard_ee_control.py`` 把两个串口写死为
``/dev/ttyACM0`` 与 ``/dev/ttyACM1``。本包装器按控制板唯一 USB 序列号
解析 macOS / Windows / Linux 的当前端口，并仅在内存中替换这两行后执行
官方脚本；逆运动学、按键映射和运动控制逻辑均保持官方原样。

运行前：两条臂必须固定、接好 12V，且运动范围内没有障碍物。官方脚本会
在开始时让两臂自动归零约三秒。
"""

from pathlib import Path

from portutil import BOARDS, resolve_port


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    official = root / "external/XLeRobot/software/examples/2_dual_so100_keyboard_ee_control.py"
    source = official.read_text(encoding="utf-8")

    white_port = resolve_port(BOARDS["white"])
    black_port = resolve_port(BOARDS["black"])
    print("运行官方双臂末端控制逻辑：")
    print(f"  arm1（白臂）: {white_port}")
    print(f"  arm2（黑臂）: {black_port}")

    source = source.replace(
        'arm1_port = "/dev/ttyACM0"', f"arm1_port = {white_port!r}", 1
    ).replace(
        'arm2_port = "/dev/ttyACM1"', f"arm2_port = {black_port!r}", 1
    )
    namespace = {"__name__": "__main__", "__file__": str(official)}
    exec(compile(source, str(official), "exec"), namespace)


if __name__ == "__main__":
    main()
