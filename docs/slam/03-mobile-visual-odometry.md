# Phase 3：移动 RGB-D visual odometry

## 目标与边界

本阶段只验证固定 Gemini 下，RTAB-Map RGB-D odometry 能否在人工低速移动时输出
`odom -> base_link`。它不启动 RTAB-Map mapping、导航、ACT、VLA，也不映射底盘或
机械臂控制板。静止 VO 通过不代表移动 VO、闭环或建图通过。

数据流为：

```text
Gemini RGB + aligned depth -> rgbd_odometry -> odom -> base_link -> JSONL -> motion metrics
                                  ^
                         static base_link -> camera_link candidate
```

相机内部 TF 仍由 Orbbec 发布；候选 base-to-camera 静态 TF 只允许在云台固定在保存
raw 参考位时使用。

## 外参状态

当前配置是 `configs/slam/base_to_gemini_unresolved.yaml`。它记录已确认的 frame 名称、
Gemini raw 参考位和最小缺失信息，但没有虚构平移或四元数。详见
`base-camera-transform-inventory.md`。`unresolved` 可以用于 dry-run；live 模式必须拒绝。

未来 candidate 配置必须是 JSON-compatible YAML，并含：`parent_frame=base_link`、
`child_frame=camera_link`、单位 `m`、三元平移、单位四元数、gimbal raw reference、来源
文件和不确定度/测量注记。解析器拒绝倒置 frame、mm、NaN/Inf、零或未归一化四元数。

## 无硬件验证

在 Jetson 正式仓库中，以下命令只读挂载代码到 SLAM 镜像；不挂载 `/data`、Gemini 或
串口，也不取得硬件锁：

```bash
./scripts/jetson_slam_motion_odom.sh --dry-run
```

预期包含：

```text
UNRESOLVED transform accepted for dry-run; live mode is prohibited
PASS motion odometry dry-run; no camera or motor device was opened
```

## 未来真机入口

未来的单一受锁监督会话会调用以下容器模式：

```bash
./scripts/jetson_slam_motion_odom.sh --config configs/slam/base_to_gemini_candidate.yaml --duration 60
```

`jetson_slam_motion_odom.sh` 目前故意只允许 `--dry-run`。它不能与独立底盘键盘会话
并行：两者都会争用现有全局硬件锁。下一轮必须先设计并评审一个单一监督会话，在同一
把锁内协调 Gemini 记录和人工底盘按键，再解除该 live 阻断。届时该会话仍须只给
camera/recording 子进程映射 Gemini；底盘控制权的最小暴露范围另行评审。实时数据目录
预留为 `/home/jetsonl7/robot-data/slam/motion-odom/<UTC>/`。

## 输入、输出、验收与回退

| 项目 | 内容 |
| --- | --- |
| 输入 | 固定云台、已验证 Gemini 链路、可 live 的 candidate TF、清空且有人监护的路线 |
| 输出 | odom/OdomInfo JSONL、TF/ROS graph 证据、移动质量 JSON 报告 |
| 验收 | 两条消息持续且单调、>=5 Hz、<=0.5 s 间隔、0 tracking loss、有限位姿、无单帧跳变/异常速度、路径和直线/转弯统计完整 |
| 回退 | 立即停止底盘、停止本容器、保留 UTC 目录；不改外参、不放宽阈值，回到已通过的静止 VO |

移动指标不会使用“总漂移 <=20 mm”：真实移动需要路径长度、起终点、单帧跳变、速度和
分段统计。起终点误差与闭环质量在设计具体路线后单独设阈值，不能在没有距离真值时编造。

## 进入真机前仍需人工完成

1. 按 `base-camera-transform-inventory.md` 的最小数据要求补齐真机外参；
2. 复位并固定 Gemini 至 raw 7=`4062`、8=`2284`，确认不再转动；
3. 审阅 candidate 配置与现场路线；
4. 确认底盘低速限制、`Space` 停止和 12V 断电方式；
5. 清空 0.5--1 m 直线，第一轮只做静止、直行、停、原路返回。
6. 设计、审阅并实现单一硬件锁所有者的监督会话；不能同时启动两个独立容器。
