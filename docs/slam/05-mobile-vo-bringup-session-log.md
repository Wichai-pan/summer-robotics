# 实验记录：移动 RGB-D Visual Odometry 准备

- 会话日期：2026-08-13
- 分支：`codex/mobile-vo-bringup`
- 基线：`origin/main` / `4a322e0`
- 本地提交：`b4c2b99`
- 状态：软件与数据契约准备完成；真机移动未获批准且入口保持封锁

## 1. 本次目标与边界

本次将静止 Gemini RGB-D visual odometry 的已验证组件整理为移动 VO 的可测试基础，
并盘点 `base_link -> camera_link` 外参证据。目标不是运行机器人，也不是建立地图。

本次没有启动 Gemini、Docker 容器、机械臂或底盘；没有获得硬件锁、写入 Jetson 数据盘、
修改 Jetson 镜像/固件或重新标定。Jetson 只进行了 Git 与状态的只读检查。

## 2. 已知静止 VO 基线

移动准备复用的前提来自已合入 `main@4a322e0` 的静止测试记录：2026-08-12 的 60 秒
camera-only RGB-D VO 采到 447 组 odom/OdomInfo，7.454 Hz，0 次 tracking loss，最大源
时间戳间隔 0.234 s，平移漂移 1.689 mm，旋转漂移 0.221 deg，TF 契约前后均通过。

原始结果位于 `/home/jetsonl7/robot-data/slam/static-odom/20260812T124119Z/`。详见
`04-static-visual-odometry-live-results.md`。这是移动 VO 的可复用软件与相机基线，
不是移动或建图验收。

## 3. 已完成工作

| 项目 | 结果 |
| --- | --- |
| 外参证据盘点 | 完成，见 `base-camera-transform-inventory.md` |
| 当前外参配置 | `unresolved`，未填写猜测数值 |
| candidate 配置解析器 | 完成，验证单位、frame、平移、四元数、云台 raw、来源与测量注记 |
| 变换数学 | 完成逆变换和组合测试 |
| 移动 VO 指标 | 完成路径、起终点、速度/跳变、tracking loss、消息质量和直线/转弯统计 |
| 静止链路复用 | 复用 Gemini 参数、RTABMap odometry、JSONL、图契约、异常清理 |
| ROS 图契约 | 支持预期 `odom -> base_link` 与唯一命名的静态 TF 发布者 |
| dry-run | 设计完成并脚本级测试为只读，不映射 `/data`、Gemini 或串口，不取锁 |
| live 入口 | 故意封锁，等待单一硬件锁监督会话设计 |

实现入口和文档：

- `scripts/jetson_slam_motion_odom.sh`
- `tools/slam_base_camera_transform.py`
- `tools/slam_motion_odom_metrics.py`
- `docs/slam/03-mobile-visual-odometry.md`

## 4. 外参证据结论

已确认的真机事实是 Gemini 云台固定抓取参考位：ID 7 raw=`4062`、ID 8 raw=`2284`；
ID 7 正向向右，ID 8 正向向下。该状态可用于让后续测量和移动测试保持相同相机姿态。

但目前没有找到能同时给出真实底盘 `base_link` 原点、Gemini `camera_link` 原点、三维平移
和完整方向关系的实机测量。因此不能唯一得到 `base_link -> camera_link` 数值。

仿真 URDF 的 `head_camera_link` 尺寸只用于结构对照，不能直接写入真机 ROS 配置。黑臂
eye-to-hand 拟合文件明确为 `diagnostic_only`、`motion_locked=true`，而且 holdout error 为
93.4 mm；它不参与 SLAM 外参。

因此提交的 `configs/slam/base_to_gemini_unresolved.yaml` 没有 `translation_m` 或
`rotation_xyzw`。它可以被 dry-run 读取并明确报告“live prohibited”；任何 live 验证都会
在启动 TF、相机或 RTABMap 前失败。

## 5. 测试与审阅

本地完成：

- Python 编译：通过；
- 28 组移动 VO 纯 Python 测试：通过；
- WSL `bash -n`：移动 wrapper、共享 odometry 容器脚本、静止 wrapper 均通过；
- unresolved 配置：dry-run 接受，live 拒绝；
- dry-run 脚本源码测试：确认只读代码挂载，且没有 Gemini、串口、`/data` 或
  `jetson_slam_exec.sh` 调用。

双轴审阅发现并已处理：

1. 原先 Gemini 记录与独立底盘键盘会争用同一硬件锁；live wrapper 已封锁。
2. 缺失 `OdomInfo` 字段改为输出可审计 FAIL，而非异常退出。
3. unresolved 外参在共享容器脚本入口增加显式 live 拒绝，避免 process-substitution
   吞掉错误状态。
4. 非有限/未归一化位姿、无效云台 raw、移动转弯统计、静态 TF 发布者与 dry-run 安全
   边界均增加测试保护。

未运行 Jetson Docker dry-run：本次边界要求不得启动容器。未运行任何 Gemini 或真机
live 入口。

## 6. 当前阻塞与风险

移动 VO 尚不能真机运行，存在两个明确阻塞：

1. 缺少经过团队确认的真机 `base_link -> camera_link` 外参；
2. Gemini 录制与人工底盘键盘控制都复用全局硬件锁，不能用两个独立容器并行启动。

静止 VO 通过仅证明固定相机下的 RGB-D odometry 稳定，不能证明移动过程中没有运动模糊、
tracking loss、路径尺度误差或闭环失败。移动指标也不以“总漂移 <=20 mm”作为通过条件。

## 7. 下一次接续顺序

1. 人工固定 Gemini 到 raw 7=`4062`、8=`2284`，确认相机支架无松动。
2. 在真实机器人上确认 `base_link` 物理原点与 X 前/Y 左/Z 上方向；拍顶视标记照片。
3. 测量 Gemini 机身参考点相对该原点的 X/Y/Z、高度、朝向和测量误差；保留照片/草图。
4. 将测量整理为 candidate 配置，并先运行无设备配置验证。
5. 设计一个单一硬件锁所有者的监督会话，在同一锁内协调 Gemini 记录和人工底盘控制。
6. 获得单独现场授权后，才做静止、短直线、停止、原路返回的低速移动 VO 测试。

失败回退：立即停止底盘，停止监督会话，保留 UTC 数据目录；不修改外参、不放宽门槛，
回到已通过的 camera-only 静止 VO 基线。

## 8. 会话结束状态

本次结束时，Jetson 正式仓库仍在 `main@4a322e0`。只读检查观察到容器
`inspiring_jepsen` 正在运行且硬件锁忙；它不属于本次工作，没有停止或干预。ACT worktree
有未提交的队友改动，本次未读取、修改或覆盖。
