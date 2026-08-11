# 实验记录：Jetson RGB-D SLAM 基础环境与相机链路

- 日期：2026-08-11
- 分支：`codex/base-terminal-slam-preflight`
- 基线：`origin/main` / `a87ee90`
- 工作目录：`D:\summer-robotics-slam`
- 当前阶段：Phase 0 已通过；Phase 1 相机链路已验证、完整验收未关闭；尚未运行视觉里程计或建图

## 1. 目标与边界

本轮建立一条不污染 ACT/LeRobot 环境的 SLAM 基础链路：

1. 验证三轮底盘能够经 SSH 安全手动控制；
2. 构建独立 ROS 2 Humble + Orbbec + RTAB-Map 镜像；
3. 只映射 Gemini 335，验证 RGB、对齐深度、IMU、TF 与 rosbag；
4. 为下一阶段静止视觉里程计测试准备可复现入口。

本轮明确没有执行：

- 自动导航或无人移动；
- RTAB-Map 视觉里程计或建图；
- 机械臂运动、重新标定、ACT/VLA 修改；
- Gemini 固件升级；
- Jetson 宿主 APT/Python 修改；
- 修改或覆盖 `/home/jetsonl7/summer-robotics-deploy` 中的队友文件。

## 2. 技术路线依据

XLeRobot 0.3.0 官网没有完整 SLAM 教程。官网可作为整机结构、遥操作和
相机稳定性要求的依据，但其 RGB-D 选件是 RealSense D415，不能直接复制到
本项目的 Orbbec Gemini 335。

当前组合为：

| 层 | 采用内容 | 依据 |
| --- | --- | --- |
| 底盘 | XLeRobot 三全向轮运动学 | 项目固定的 XLeRobot 上游源码与真机方向测试 |
| 相机 | OrbbecSDK ROS 2 Wrapper v2 | 官方支持 Gemini 335 与 ROS 2 Humble |
| SLAM | RTAB-Map ROS 2 | 官方提供 RGB-D 视觉里程计与建图组件 |
| 执行环境 | Jetson 独立 Docker 镜像 | 避免污染现有 LeRobot/ACT 镜像 |

`slam_toolbox` 不是第一路线，因为它要求已验证的二维激光 `/scan`，当前项目
没有已验收的 LiDAR。第一张图先用 RGB-D visual odometry，轮速里程计后置。

## 3. 隔离设计

| 对象 | SLAM 处理方式 | 结果 |
| --- | --- | --- |
| 现有镜像 | 保留 `forestbridge-xlerobot:jp62` | 未修改 |
| 新镜像 | `forestbridge-xlerobot:slam-humble` | 独立构建，约 3.41 GB |
| Jetson 宿主环境 | 不执行宿主 `apt install` / `pip install` | 未修改 |
| 标定缓存 | 只读或不映射 | 未修改 |
| 电机串口 | 相机预检不映射 `/dev/ttyACM*` | 无运动能力 |
| Gemini | 通过 `jetson_robot_exec.sh --gemini` 映射 | 复用设备解析与全局锁 |
| 输出数据 | `/home/jetsonl7/robot-data/slam/` | Git 外保存 |
| 临时构建上下文 | `/home/jetsonl7/robot-data/tmp/slam-build/` | 不覆盖部署仓库 |

所有硬件入口继续复用 `/tmp/forestbridge-xlerobot.lock`。相机预检曾在 ACT
rollout 占用 Gemini 时被正确拒绝；没有停止或干扰队友任务。

## 4. Phase 0：底盘命令链验收

### 输入

- 机器人可靠垫高，三个轮子完全离地；
- 白板序列号 `5B3D040988`；
- 现场可立即断开 12V；
- SSH 终端控制器 `tools/base_keyboard.py --terminal`。

### 结果

- 白板稳定解析为 `/dev/ttyACM0`；
- `W/S` 前后、`A/D` 横移、`Q/E` 旋转方向全部正确；
- `Space` 停车、`X/Esc` 退出可用；
- SSH 模式按键停止重复后 250 ms 自动发零速度；
- 退出时写零速度、松轮子扭矩、关闭串口。

### 上游一致性

项目固定的 XLeRobot commit
`3d14695e40c9c68229c0aacffca6053c75cd3eb6` 使用：

- 轮半径 `0.05 m`；
- 底盘半径 `0.125 m`；
- 安装角 `[240, 0, 120] - 90 deg`；
- 左轮、后轮、右轮顺序；
- 与本工具一致的 `x/y/theta` 正负方向。

整机官方键盘使用 `I/K/J/L/U/O`，因为其他按键用于双臂。本工具是独立底盘
入口，所以使用等价的 `W/S/A/D/Q/E`。

## 5. Phase 1：独立镜像构建

### 构建命令

```bash
docker build -f deploy/slam/Dockerfile \
  -t forestbridge-xlerobot:slam-humble .
```

### 实际版本

| 组件 | 版本 |
| --- | --- |
| ROS 2 | Humble / Ubuntu 22.04 arm64 |
| Orbbec camera | `2.8.6` |
| Orbbec description | `2.8.6` |
| RTAB-Map ROS | `0.23.7` |
| rosbag2 MCAP | `0.15.16` |

镜像 ID 前缀：`166100ba4347`。

### 零硬件 smoke

```bash
./scripts/jetson_slam_software_smoke.sh
```

验收内容：包可发现、Gemini 330 系列 launch 存在、深度对齐和同步 IMU 参数
存在。该命令不映射设备或宿主目录，结果为 `PASS`。

## 6. Gemini ROS 预检过程

### 6.1 硬件对齐失败记录

第一次启用 `align_mode:=HW` 时：

- 相机型号、序列号和 USB 3.2 连接均识别成功；
- 加速度计和陀螺仪以 200 Hz 启动；
- 当前 stream profile 被固件拒绝硬件 Depth-to-Color 对齐；
- 错误为 `Current stream profile is not support hardware d2c`。

该失败未被隐藏。我们只停止了自己启动的 Gemini-only 容器，并补强了相机
进程组的 INT -> TERM -> KILL 清理。没有映射或控制电机。

当前 Gemini 固件为 `1.4.60`。官方当前推荐版本更高，但本轮没有获得固件升级
授权，因此没有升级或刷写。

### 6.2 软件对齐链路通过

将 Orbbec 官方支持的 `align_mode:=SW` 用于当前 profile 后通过：

| 数据 | 实测结果 |
| --- | --- |
| RGB | 1280x720、`rgb8`、约 29 Hz |
| Depth | 1280x720、`16UC1`、约 29 Hz |
| 对齐目标 | `camera_color_optical_frame` |
| 同步 IMU | `camera/gyro_accel/sample`、约 192 Hz |
| 预检时长 | 8.12 秒有效 rosbag |
| 消息总数 | 2506 |
| 日志 | 无 warning/error |

MCAP 位于：

```text
/home/jetsonl7/robot-data/slam/preflight/20260811T131318Z/
```

约 8 秒的未压缩 RGB-D bag 已达到约 1.0 GiB。后续不要无目的长时间录制；
正式诊断应设置明确时长，并监控磁盘。

### 6.3 相机内部 TF

无 bag 的复核运行验证了以下内部链路：

```text
camera_link
  -> camera_depth_frame
     -> camera_color_frame
     -> camera_depth_optical_frame
     -> camera_accel_frame
     -> camera_gyro_frame
  -> camera_color_optical_frame
  -> camera_accel_gyro_optical_frame
```

该链路仅覆盖相机内部坐标系。`base_link -> camera_link` 尚不存在，不能宣称
机器人 TF 或建图外参已经完成。

### 6.4 Phase 1 尚未关闭的验收项

现有脚本和 MCAP 已证明 topic 可用、分辨率/编码正确、短时消息数量合理、相机
内部 TF 存在，但以下项目尚未形成自动化或可复核的量化结果：

1. 实测并记录深度单位与已知距离误差；
2. 统计 RGB 与对齐 Depth 的时间戳差；
3. 统计持续帧率和掉帧，而不只使用消息总数估算；
4. 确认 ROS graph 中只有一个相机驱动节点拥有这些 topic。

因此本记录只将“Phase 1 相机链路预检”标为通过，不将 Phase 1 的全部验收项
标为完成。上述四项必须在 Phase 2 前关闭。

## 7. 已知风险

1. Gemini 云台可动。建图时必须锁定并标记姿态，否则外参随时间变化。
2. 当前使用软件对齐，会增加 CPU 开销；后续可以另行寻找兼容硬件 profile。
3. 固件 `1.4.60` 低于当前官方建议，但不能未经审批升级。
4. 尚未测量 `base_link -> camera_link` 实机外参。
5. 底盘没有 ROS wheel odometry；纯 RGB-D 在白墙、反光、暗光和快速旋转时
   可能丢失跟踪。
6. 还没有运行 RTAB-Map odometry、闭环检测、2D map 或 3D cloud 导出。
7. 当前 SLAM 文件只在本分支；Jetson 部署仓库尚未切换到该提交。
8. Phase 1 的深度尺度、RGB-D 时间差、持续帧率和唯一相机 owner 尚待量化。
9. 镜像基底已固定 digest，但 ROS APT 包没有使用快照仓库；未来重建时包版本
   可能变化，必须重新运行 software smoke 并记录版本。

## 8. 下一阶段门槛

进入静止视觉里程计前，先完成 6.4 节的四项相机 QA；然后现场必须完成：

1. 在头部电机松扭矩或 12V 关闭时调整 Gemini；
2. pan 正前方，tilt 轻微向下，同时看到地面和远处竖直结构；
3. 拧紧安装件，轻触不晃动；
4. 用胶带或记号标记 pan/tilt；
5. 保存机器人正面和相机侧面照片；
6. 确认没有 ACT、相机或其他硬件任务占锁。

操作者确认“Gemini 云台已固定并标记”后，才运行相机坐标系下的静止
RTAB-Map RGB-D odometry 漂移测试。该测试不移动机器人。

## 9. 回退方法

- 相机异常：停止本次 `forestbridge-xlerobot:slam-humble` 容器；不要删除锁文件。
- 镜像回退：删除或停止使用独立 SLAM 镜像即可，原 ACT 镜像不受影响。
- 数据回退：只隔离对应 UTC 时间目录，不改其他实验数据。
- 硬件异常：立即停止程序；出现机械异常时切断 12V。
- 不执行：`git reset --hard`、覆盖队友仓库、固件刷写或宿主大规模安装。

## 10. 上游资料

- XLeRobot 0.3.0：https://xlerobot.readthedocs.io/zh-cn/latest/
- XLeRobot 遥操作：https://xlerobot.readthedocs.io/zh-cn/latest/software/getting_started/XLeRobot_teleop.html
- Orbbec ROS 2：https://github.com/orbbec/OrbbecSDK_ROS2
- RTAB-Map ROS 2：https://github.com/introlab/rtabmap_ros

## 11. 提交前审阅与验证

本分支在提交前分别做了工程规范审阅和需求符合性审阅。发现并修正：

- 输入后端初始化失败前不应使能轮子扭矩；
- 退出时一个清理动作失败不能阻止其他轮子写零速度、卸扭矩和关闭串口；
- 机械臂 SDK 的通信错误不能被忽略或仍打印“成功关闭”；
- Phase 1 预检通过不能写成 Phase 1 全部验收完成；
- 外部 TF 根统一使用 Orbbec 实际发布的 `camera_link`；
- 新增 shell 脚本提交时必须保留可执行位。

本地最终检查：

- `python -m py_compile tools/base_keyboard.py tests/test_base_keyboard.py`：通过；
- `python tools/base_keyboard.py --dry-run`：通过，未导入串口 SDK；
- 六个无硬件测试函数：全部通过，包括输入初始化失败和清理故障路径；
- `git diff --check`：通过；
- 当前电脑没有安装 `pytest`，因此用直接导入并逐个调用测试函数的方式运行，
  没有为本次提交安装依赖。

Jetson 上同一镜像的 software smoke、Gemini 预检和锁释放检查此前已通过。本次
提交收尾时 Jetson 的 `.local`、局域网 IP 和已知 Tailscale IP 均不可达，因此
没有把旧结果表述为本次重新运行；恢复连接后可按复核清单重复无硬件 smoke。
