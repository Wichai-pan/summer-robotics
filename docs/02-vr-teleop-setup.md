# 实验记录 02 · VR 遥操作 setup（软件已就绪）

- **日期**：2026-06-17
- **状态**：软件 setup ✅ 完成并验证；真机运行待【硬件健康 + Quest + WiFi】

## VR 怎么工作

```
你的手（Quest 控制器）
  → Quest 浏览器里的 WebXR 网页，读控制器 3D 位姿 + 扳机
  → WiFi (WebSocket)
  → Mac 上 vr_monitor.py（HTTPS :8443 / WS :8442）→ left_goal / right_goal
  → 逆运动学 SO101Kinematics：目标位置 → 关节角度
  → 舵机总线
左控制器→左臂   右控制器→右臂   扳机→夹爪   头显→头部电机
```

## 已完成的软件 setup（自动化部分）

- **XLeRobot 文件整合**：`software/src/model/SO101Robot.py` → `lerobot/model/`；`software/src/robots/xlerobot` → `lerobot/robots/`。import 已验证通过。
- **依赖**：`pip install pygame scipy websockets`（torch/numpy/pyyaml/pynput 已有）。
- **`XLeVR/vr_monitor.py` 的 `XLEVR_PATH`** 改成本机绝对路径。
- **`config_xlerobot.py` 的 port1/port2** 改成【按板序列号自动解析】：
  - `port1` = 黑板 `5B3D043224`（左臂 1-6 + 头 7,8）
  - `port2` = 白板 `5B3D040988`（右臂 1-6 + 底盘 7,8,9）
- **启动器 [`tools/vr_teleop.py`](../tools/vr_teleop.py)**：设好 sys.path 后运行官方 `8_xlerobot_teleop_vr.py`。
- 整条 import 链（`vr_monitor` / `xlerobot` / `precise_sleep` / `SO101Kinematics` / `pygame`）验证通过。

> 注：以上改动在 `external/`（已 gitignore），属本机集成。队友复现需重做整合 + 改各自的 `XLEVR_PATH` 和板序列号。

## 运行前提（缺一不可）

1. **两块板都接好**（12V + USB）：黑板 = 左臂 + 头；白板 = 右臂 + 底盘。
2. **整机首次连接会自动标定全部关节**（双臂各掰一遍量程）——和单臂标定同套路。
3. **Quest 3S 与 Mac 同一 WiFi**（本机 IP 当前 `192.168.0.219`，会变；用 `ipconfig getifaddr en0` 查）。

## 运行步骤

```bash
conda activate lerobot
cd ~/Wichai/Hackathons/summer-robotics
python tools/vr_teleop.py
```

- 终端会打印 `https://<Mac-IP>:8443`。
- **Quest 浏览器打开那个地址** → 自签证书会警告“不安全”，点**继续/高级→继续** → 进入 VR/immersive → 移动控制器，双臂跟随。

## 已知坑

| 现象 | 说明 |
|---|---|
| 一堆 `objc[...] SDL2 implemented in both` 警告 | cv2 和 pygame 都带 SDL2，**无害噪声**，忽略 |
| Quest 浏览器报“不安全” | 自签证书，点继续即可 |
| 首次连接要标定一大堆关节 | 整机标定（16-17 个），需**两块板都健康**；白板若还接触不良，先修线 |
| 深度相机没到 | **不影响 VR 控制手臂**；只影响“采训练数据的相机画面”，可先用 RGB 起步 |

## 下一步

VR 遥操作跑通后 → 用 `external/XLeRobot/software/examples/8_vr_teleop_with_dataset_recording.py`（或 `lerobot-record`）**边 VR 遥操作边录数据集** → 进入训练阶段。
