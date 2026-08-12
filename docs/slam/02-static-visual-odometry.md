# Phase 2：camera-only 静止 RGB-D visual odometry

- 分支：`codex/base-terminal-slam-preflight`
- 状态：代码与无硬件验证完成；尚未打开 Gemini，尚未运行真实静止测试
- 算法：`rtabmap_odom/rgbd_odometry`
- 参考坐标系：`camera_link`

## 1. 目标与边界

本阶段只回答一个问题：机器人和 Gemini 完全静止时，RGB-D visual odometry
能否持续输出稳定、有限且不丢失的位姿。

本阶段不包含：

- 底盘或机械臂运动；
- 完整 RTAB-Map 建图节点；
- IMU 数据流、IMU 融合或轮速融合；
- `base_link -> camera_link` 外参接入；
- 重新标定 Gemini、重新采集 IK 标定或修改固件；
- RGB-D 视频录制。

## 2. 数据流

```text
Gemini 335
  -> /camera/color/image_raw
  -> /camera/depth/image_raw（软件对齐到 color optical frame）
  -> /camera/color/camera_info
  -> rtabmap_odom/rgbd_odometry
  -> /rtabmap/odom
  -> /rtabmap/odom_info
  -> compact JSONL
  -> drift/quality JSON report
```

第一轮不订阅 IMU。这样如果跟踪不稳定，可以先判断 RGB-D 本身是否可靠，
不会把视觉、IMU 时间同步和融合参数混成一个问题。

## 3. 固定配置

| 项目 | 值 |
| --- | --- |
| `frame_id` | `camera_link` |
| RGB | `/camera/color/image_raw` |
| Depth | `/camera/depth/image_raw` |
| CameraInfo | `/camera/color/camera_info` |
| 同步 | approximate，最大 10 ms |
| QoS | Reliable |
| topic/sync queue | 30 |
| publish null when lost | true |
| 测试时长 | 默认 60 秒 |

10 ms 同步窗口远大于已测最大 RGB-D 时间差 0.160 ms，同时保持边界明确。

## 4. 入口

零硬件 dry-run：

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_slam_static_odom.sh --dry-run
```

该模式只把仓库只读挂入一次性 SLAM 容器，不映射 `/data`、Gemini、控制板，
也不获取硬件锁。它验证 ROS 包、`OdomInfo.lost` 字段、采集器 dry-run、指标
工具和最终 `rgbd_odometry` 参数；RTAB-Map 节点会在无输入状态下探针运行 3 秒。

未来获批的真实静止测试：

```bash
./scripts/jetson_slam_static_odom.sh --duration 60
```

真实入口固定写入 `/home/jetsonl7/robot-data/slam/static-odom/`，拒绝调用方覆盖
输出根目录。它复用 `jetson_robot_exec.sh --gemini`，所以只有 Gemini 被映射，并由
`/tmp/forestbridge-xlerobot.lock` 独占保护。没有控制板串口，程序没有运动能力。

## 5. 输出与验收

输出目录：

```text
/home/jetsonl7/robot-data/slam/static-odom/<UTC timestamp>/
```

关键文件：

- `static-odom.jsonl`：紧凑 odometry 与 `OdomInfo` 样本；
- `static-odom-report.json`：漂移、消息/接收频率、最大间隔、frame 契约和
  tracking loss 结论；
- `orbbec-camera.log`；
- `rtabmap-rgbd-odometry.log`；
- `nodes.txt`、topic publisher/subscriber 信息；
- `tf-topic-info.txt`、`tf-static-topic-info.txt` 及各自的一帧样本。

第一轮门槛：

| 指标 | 门槛 |
| --- | ---: |
| 有效时长 | 至少命令时长的 80% |
| odometry 平均频率 | >= 5 Hz |
| 最大时间戳间隔 | <= 0.5 s |
| 最大单调接收间隔 | <= 0.5 s |
| `OdomInfo` | 持续存在，>= 5 Hz |
| frame contract | `odom -> camera_link` |
| TF ownership | `/tf` 仅由 `rgbd_odometry` 发布；`/tf_static` 仅由 `camera` 发布 |
| 最大平移偏移 | <= 0.020 m |
| 最大旋转偏移 | <= 1.0 deg |
| tracking-loss transition | 0 |

使用“最大偏移”而不只比较首尾位姿，避免轨迹先漂移、后返回原点而被误判通过。

## 6. 无硬件验证结果

2026-08-12 已完成：

- Python 编译通过；
- 七组纯指标测试通过：稳定轨迹、漂移/丢失、消息时间戳断档、odometry 接收
  停顿、`OdomInfo` 接收停顿、`OdomInfo`/frame 契约缺失、四元数符号；
- 两个 shell 脚本 `bash -n` 通过；
- 目标 Jetson SLAM 镜像内的 3 秒 RTAB-Map 参数探针通过；
- dry-run 结束后无容器残留，全局硬件锁为空。

预期结束文本：

```text
PASS static odometry dry-run; no camera or motor device was opened
```

## 7. 回退与下一门槛

- dry-run 失败：只修复包、参数或脚本，不打开 Gemini；
- 真实测试失败：保留对应 UTC 目录，停止容器，不调标定、不移动底盘；
- tracking loss：先检查图像停顿、纹理和 CPU 负载，再讨论分辨率或算法参数；
- 静止测试通过后，才设计低速、短距离、现场监督的相机轨迹测试。

运行真实 `--duration 60` 前，现场人员必须确认底盘完全静止、Gemini 云台沿用
IK/ACT 固定姿态且不会晃动，并确认没有 ACT 或其他相机任务占用硬件锁。
