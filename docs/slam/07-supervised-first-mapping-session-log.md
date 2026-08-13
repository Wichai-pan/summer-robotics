# 实验记录：首次监督式移动 RGB-D 建图

- 日期：2026-08-13
- 分支：`codex/supervised-slam-mapping`
- 状态：端到端建图链路已在真机运行并保存数据库；地图仅为短直线初步结果，尚不是可用于导航的房间地图。

## 1. 本次目标与边界

目标是在 **Gemini 云台固定** 的前提下，让底盘由现场操作者低速手动控制，并由同一受锁
会话同时运行 Orbbec ROS 2、RGB-D visual odometry 和 RTAB-Map。所有底盘动作仍需现场人员和
12 V 断电手段；本次没有运行自主导航、Nav2、机械臂、IK 或 ACT。

本轮使用的候选外参、帧定义和固定云台条件见
[`06-base-camera-candidate-measurement.md`](06-base-camera-candidate-measurement.md)。

## 2. 固定云台与外参状态

现场将 Gemini 调到近似水平、正前方并保存为 SLAM 参考位：

| 项目 | 值 |
| --- | --- |
| 参考文件（Jetson host） | `/home/jetsonl7/robot-data/config/gemini_gimbal_level_forward_v1.json` |
| 参考文件（容器） | `/data/config/gemini_gimbal_level_forward_v1.json` |
| yaw，黑板 ID 7 raw | `4068` |
| pitch，黑板 ID 8 raw | `1694` |
| 使用的 candidate `base_link -> camera_link` 平移（m） | `[-0.04913, 0.02500, 1.18250]` |
| 使用的旋转 | identity quaternion `[0, 0, 0, 1]` |

raw 编码器值是唯一权威的可复现姿态记录；显示的 one-turn 角度不是世界角度。建图期间不得
移动云台。若今后要在建图时扫视，必须发布云台关节状态及动态 `base_link -> camera_link` TF，
不能继续使用本次静态外参。

## 3. 运行入口与可靠性修正

监督式入口：

```bash
cd /home/jetsonl7/robot-data/tmp/slam-supervised-mapping
bash scripts/jetson_slam_supervised_mapping.sh --duration 120
```

该入口在同一个硬件锁内完成：云台参考位只读检查、candidate TF 检查、ROS 图启动、RTAB-Map
记录、底盘终端输入和工件收尾。底盘输入为 `W/S` 前后、`A/D` 横移、`Q/E` 旋转、Space 停止、
`X`/Esc 退出；终端 dead-man 为 250 ms。

本次修正了两个实际发现：

1. 底盘早期会在 `BASE` 后向右转。原因是断扭矩时残留的 wheel `Goal_Velocity` 在重新上扭矩
   后被执行。现在在使能底盘扭矩前，先通过组写清零三轮速度目标。
2. 逐个轮子高频写速度会出现偶发 `communication=-6` / 无状态包。现在使用三轮组写，降低
   状态包拥塞；仍保留失败即停止与松扭矩的退出路径。

出现过一次临时 gimbal `No status packet` 以及早期底盘通信超时；重新插稳供电/数据线后可以
继续。它们应视为接线/供电健康风险，下一次移动前先做只读状态检查。

## 4. 已保存的建图结果

所有数据库和大文件都保存在 Jetson `/home/jetsonl7/robot-data/slam/mapping/`，不提交 Git。

| 会话 | 结果 | 备注 |
| --- | --- | --- |
| `20260813T144318Z` | `rtabmap.db` 已保存 | 首次短路线；指标未达预设质量门槛，主要用于验证全链路和工件写入。 |
| `20260813T153639Z` | `rtabmap.db` 已保存并导出 | 本次较稳定的短直线移动；数据库约 131 MB，导出为 `export/map.pgm`、`map.yaml`、`map_poses.txt`。 |

第二次会话的观测结果：

- 运行 `119.91 s`，无 tracking-loss 事件；
- 里程计/`odom_info` 共 560 条，`4.67 Hz`；中位特征数 `935`、中位 inliers `357`；
- 估计路径长 `1.323 m`，结束位姿约为 `[0.649, 0.106, 0.008] m`；
- 最大单步平移 `0.0196 m`、最大角速度 `5.38 deg/s`；
- TF 和 topic publisher 契约在起止检查均通过。

质量报告仍标为 `FAIL`，但原因是保守门槛 `>=5.0 Hz` 与最大接收间隔 `<=0.50 s`，实测为
`4.67 Hz` 与 `0.516 s`；不是 tracking 丢失，也不是地图保存失败。门槛先不放宽：下一次应先
用更平稳、有效移动的完整路线重新测量，再根据多次结果决定合适的基线。

本次现实移动大约为短距离前进，并不是闭环路线；画面中还有移动人员。因此当前数据库能证明
**传感器—里程计—RTAB-Map—保存—本地查看** 完整可用，但不能声称地图几何已经可靠，亦不能用
于自主导航。

## 5. 本地查看

远程 XQuartz 的 Qt/OpenGL 3D view 出现 `makeCurrent()` 失败，因此改为在 Mac 原生查看。
Homebrew 已安装 RTAB-Map，命令为：

```bash
rtabmap-databaseViewer \
  ~/Downloads/forestbridge-maps/rtabmap_20260813T153639Z.db
```

3D view 中 `Cloud` 显示彩色点云，`Map` 显示占据栅格，`Odom` 显示估计轨迹。若需移动的是
**查看视角而不是机器人**，在 3D 窗口右键选择 `Camera -> Free`，然后使用方向键平移、
Shift + 上下键升降、Shift + 左右键改变朝向、鼠标左拖旋转、滚轮缩放、中键拖动平移。

## 6. 下一次接续

1. 将云台回到 raw `7=4068, 8=1694`，运行只读检查；整次 mapping 不动云台。
2. 清空视野中来回走动的人，保证光照和场景静态。
3. 现场操作者按低速路线：静止约 3 s → 前进 0.5–0.7 m → 静止 → 转约 90° → 再前进；
   最终形成 1–2 m 小闭环并回看起点。
4. 保留每次 UTC 数据目录，导出并对比 `map.pgm`、轨迹与质量 JSON；不要覆盖本次数据库。
5. 闭环地图稳定后，才讨论 RTAB-Map map 的命名抓取点、Nav2 规划和底盘局部避障。
