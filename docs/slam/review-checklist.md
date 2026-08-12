# SLAM bring-up 队友复核清单

本清单用于审阅 `codex/base-terminal-slam-preflight`。默认只做静态或无硬件
检查；带 Gemini 的命令必须先确认全局硬件锁空闲。

## 1. Git 范围

```bash
git status --short --branch
git diff origin/main...HEAD --stat
git diff origin/main...HEAD --check
```

确认：

- 分支不是 `main`；
- 没有数据、模型、标定缓存或相机输出进入 Git；
- 改动只包含底盘终端控制、SLAM 容器/脚本、测试和文档。

## 2. 底盘代码（无硬件）

```bash
python tools/base_keyboard.py --dry-run
python -m pytest -q tests/test_base_keyboard.py
```

确认：

- dry-run 不导入 `scservo_sdk` 或打开串口；
- W/S、A/D、Q/E 成对反向；
- 轮序为 ID 7/8/9；
- terminal dead-man 为 250 ms；
- `Space` 与 `X/Esc` 进入停止状态。

## 3. SLAM 镜像（无硬件）

```bash
docker image inspect forestbridge-xlerobot:slam-humble \
  --format '{{.Id}} {{.Size}}'
./scripts/jetson_slam_software_smoke.sh
```

预期 smoke 最后一行为：

```text
PASS isolated SLAM software smoke; no hardware was mapped
```

## 4. Gemini 预检（需要独占相机）

先检查：

```bash
docker ps
flock --nonblock /tmp/forestbridge-xlerobot.lock true
```

退出码非零表示有任务占用硬件，不要删除 lock 文件或抢占容器。

默认预检会生成约 1 GiB/10 秒的 RGB-D MCAP：

```bash
./scripts/jetson_slam_camera_preflight.sh
```

只复核 topic/TF、不录 bag 时：

```bash
FORESTBRIDGE_IMAGE=forestbridge-xlerobot:slam-humble \
  ./scripts/jetson_robot_exec.sh --gemini -- \
  bash scripts/slam_camera_preflight_container.sh /data/slam/preflight 0
```

确认容器参数中只有 `--gemini`，没有 `--white` 或 `--black`。

## 5. 输出验收

检查最新目录：

```bash
find /home/jetsonl7/robot-data/slam/preflight \
  -mindepth 1 -maxdepth 1 -type d | sort | tail -1
```

确认：

- RGB 与 Depth 都是 1280x720；
- depth frame 是 `camera_color_optical_frame`；
- `/camera/gyro_accel/sample` 有数据；
- `/tf_static` 包含相机内部 frame；
- `orbbec-camera.log` 没有 warning/error；
- 退出后 `docker ps` 无 SLAM 容器，硬件锁可重新获取。

新版预检还会保存：

- `nodes.txt`；
- RGB / Depth 的 `*_info.txt`，且 `Publisher count` 必须为 1；
- RGB / Depth / IMU 的 `*_hz.txt`；
- `depth-scale-parameter.txt`。

相机链路 QA 已记录：

- RGB 与对齐 Depth 的时间戳差分布；
- 一段固定时长内的实际帧率、P95/最大间隔和掉帧；
- ROS graph 中相机驱动节点唯一，没有重复 owner。

2026-08-11 已关闭以上三项；证据见
`/home/jetsonl7/robot-data/slam/preflight/20260811T131318Z/` 和
`20260811T172703Z/`。驱动同时确认启用深度缩放、默认精度为 1 mm。

结合已有 IK/ACT 实机证据，现有结果足以进入 camera-only 静止视觉里程计，
不再要求新的已知距离检查或相机重标定。正式 TF 优先复用并转换已有安装测量；
不得把失败的 `motion_locked` eye-to-hand 拟合直接发布为 TF。

## 6. 必须阻止合并的情况

- 脚本绕过 `jetson_robot_exec.sh` 或全局硬件锁；
- 相机预检映射电机串口；
- 固件升级或标定修改混入本提交；
- 将 `/home/jetsonl7/robot-data/` 内容加入 Git；
- 把仿真 URDF 的相机位姿宣称为实机外参；
- 文档宣称已经完成视觉里程计、建图或自主导航。

## 7. 静止视觉里程计（默认只做 dry-run）

无硬件检查：

```bash
./scripts/jetson_slam_static_odom.sh --dry-run
```

该检查使用独立 ROS domain。确认输出以以下文字结束：

```text
PASS static odometry dry-run; no camera or motor device was opened
```

真实的 `--duration 60` 需要现场人员另行确认 Gemini 云台固定、底盘静止且硬件
锁空闲。入口必须只映射 `--gemini`，不得映射 `--white` 或 `--black`。当前阶段
不得启动完整 RTAB-Map 建图节点、IMU 数据流/融合或底盘运动。真实入口的输出根
目录固定为 `/home/jetsonl7/robot-data/slam/static-odom/`，且必须验证 odometry topic
与 `/tf` 均由 `rgbd_odometry` 唯一发布、`/tf_static` 由相机节点唯一发布，并用
`tf2_echo` 验证真实 `odom -> camera_link` 链。失败运行也必须保留机器可读报告。
