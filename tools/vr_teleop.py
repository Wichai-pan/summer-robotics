"""启动 VR 遥操作（整机：双臂 + 底盘 + 头）。

前提（缺一不可）：
  1. 两块电机板都接好（12V + USB）：黑板 = 左臂(1-6)+头(7,8) = port1；
     白板 = 右臂(1-6)+底盘(7,8,9) = port2。（端口按板序列号自动解析）
  2. 整机【首次连接会自动标定全部关节】——按提示把两条臂各掰一遍量程。
  3. Quest 3S 与 Mac 在【同一 WiFi】。

运行后终端会打印一个 https://<Mac-IP>:8443 地址：
  用 Quest 浏览器打开 → 接受“不安全”证书（自签）→ 进入 VR/immersive →
  移动控制器，双臂跟着你的手动。扳机 = 夹爪开合。

用法：  python tools/vr_teleop.py
"""
import os
import sys
import runpy

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLEVR = os.path.join(BASE, "external", "XLeRobot", "XLeVR")
EXAMPLES = os.path.join(BASE, "external", "XLeRobot", "software", "examples")
SCRIPT = os.path.join(EXAMPLES, "8_xlerobot_teleop_vr.py")

# 让 `from vr_monitor import VRMonitor` 能找到 XLeVR 的 vr_monitor.py + xlevr 包
sys.path.insert(0, XLEVR)
sys.path.insert(0, EXAMPLES)

if not os.path.exists(SCRIPT):
    raise SystemExit(f"找不到 VR 脚本: {SCRIPT}\n（external/ 里 clone 了 XLeRobot 吗？）")

# 直接以 __main__ 方式运行官方 8_ VR 脚本（端口/路径已在上面和 config 里配好）
runpy.run_path(SCRIPT, run_name="__main__")
