# 监督式低头 Gemini 闭环建图记录（2026-08-14）

## 1. 结论

2026-08-14 已在真机完成一张可复现的、人工低速监督的 RGB-D 闭环地图。最终会话
`20260814T140025Z` 在固定低头 Gemini 姿态下运行约 360 s，视觉里程计无 tracking-loss，
起终点位置残差约 5.4 cm、姿态残差约 0.71°。

这证明 Gemini RGB-D、RTAB-Map、固定 `base_link -> camera_link` 候选外参、手动三轮底盘和
数据库工件保存可以共同完成主要活动区的闭环建图。它是后续**视觉重定位和路径规划的候选地图**，
不是已经验证过的 Nav2 自主导航地图；当前尚未接入轮速/IMU 融合里程计、localization-only
重启测试或 `/cmd_vel` 底盘桥。

## 2. 固定建图姿态

原先近似水平的高位前视相机不能充分看见前方地板，二维 occupancy grid 中机器人活动区域常
保持未知。为此新增一个与抓取姿态分开的、仅用于建图的固定云台位：

| 项目 | 值 |
| --- | --- |
| Jetson 容器参考 | `/data/config/gemini_gimbal_mapping_down_20deg_v1.json` |
| 黑板 ID 7 raw（yaw） | `4066` |
| 黑板 ID 8 raw（pitch） | `1924` |
| 相对水平 ID 8=1694 | `+230 ticks`，观测为约 `20.21°` 低头 |
| 对应外参配置 | `configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml` |
| 旋转四元数 `xyzw` | `[0, 0.175500579, 0, 0.984479308]` |

外参的平移仍继承水平位的候选值 `[-0.04913, 0.02500, 1.18250] m`。因此这份低头配置的
状态仍为 `candidate`：在使用它做监督建图前已通过配置校验，但尚未重新测量 pitch pivot 到
camera origin 的平移变化。建图过程中 Gemini 必须固定在上述 raw 参考位；不可手动扫视。
若以后要边建图边转云台，必须读取 ID 7/8、发布关节状态并发布动态
`base_link -> camera_link` TF。

## 3. 本轮可靠性修复

一次 300 s 会话 `20260814T122713Z` 仅因 RTAB-Map 运行期出现一帧零四元数姿态而被离线指标
脚本拒绝。它不是底盘或 Gemini 的 tracking-loss。采集器现会跳过位置/四元数非有限或四元数
全零的未初始化 odometry 帧，并输出 `invalid_odom_skipped` 计数；有效帧仍使用原有频率、间隔、
tracking-loss 和闭环门槛检验。

部署前保留 Jetson 旧版本：

```text
/home/jetsonl7/robot-data/backups/slam/capture_static_odom.py.before-invalid-odom-filter-20260814
```

修复后的无设备 mapping smoke test 通过。该变化不修改 RTAB-Map 参数，也不写云台、底盘或机械臂。

## 4. 代表性工件与结果

所有大工件保留在 Jetson 数据盘 `/home/jetsonl7/robot-data/slam/mapping/`，不进入 Git。

| UTC 会话 | 云台 | 结果 | 闭环/说明 |
| --- | --- | --- | --- |
| `20260814T115930Z` | 水平前视 | PASS | 约 8.06 m；位置 11.9 cm，朝向 0.06°；水平位健康基线。 |
| `20260814T130912Z` | 低头约 20° | PASS | 约 5.67 m；位置 15.1 cm，朝向 2.6°；低头后中位 inliers 提升至 435。 |
| `20260814T132723Z` | 低头约 20° | PASS | 覆盖内圈/中心，但未回正：位置约 35 cm、朝向约 129°；仅作覆盖诊断。 |
| `20260814T134451Z` | 低头约 20° | PASS | 位置约 7.8 cm，但朝向约 91.7°；证明回到起点附近但尚未完整闭环。 |
| `20260814T140025Z` | 低头约 20° | **PASS，当前候选** | 约 9.10 m；位置约 **5.4 cm**，朝向约 **0.71°**。 |

最终候选 `20260814T140025Z` 的质量指标：

| 检查 | 结果 |
| --- | ---: |
| 记录时长 | 359.794 s |
| odometry 频率 | 7.143 Hz |
| 最大消息间隔 | 0.467221 s |
| tracking-loss | 0 |
| 路径长度 | 9.100 m |
| 中位 features / inliers | 890 / 346 |
| 起终点位置残差 | 0.054 m |
| 起终点姿态残差 | 0.71° |

低头姿态与“外圈 → 内圈 → 穿过中心 → 回到起点和原朝向”的路线，使主要活动区出现连续的
已观测可通行地面。机器人正下方仍有高位前向 RGB-D 的物理盲区；这不是通过反复绕同一个圆
能够消除的。后续应由底盘 footprint/inflation 和低位近场传感补偿，而不是把未知区误标为空闲。

## 5. 查看与复现

从 Mac 下载并本地检查最终数据库：

```bash
mkdir -p ~/Downloads/forestbridge-maps

scp jetsonl7:/home/jetsonl7/robot-data/slam/mapping/20260814T140025Z/rtabmap.db \
  ~/Downloads/forestbridge-maps/rtabmap_20260814T140025Z.db

rtabmap-databaseViewer \
  ~/Downloads/forestbridge-maps/rtabmap_20260814T140025Z.db
```

Graph View 的黑色是观察到的障碍，浅色区域是观察到的空闲地面，深灰背景为未知。动态的人、
椅子和衣物可造成残影；验收时优先看墙、桌边、柜体等固定结构是否连续，以及回到起点时是否
没有复制出第二个房间。

复现当前候选姿态的建图入口：

```bash
cd /home/jetsonl7/robot-data/tmp/slam-cleanup-tuning-20260813

bash scripts/jetson_slam_supervised_mapping.sh \
  --duration 360 \
  --config configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml \
  --gimbal-reference /data/config/gemini_gimbal_mapping_down_20deg_v1.json
```

此入口仍要求现场输入 `MAP`、`BASE`，保持 12 V 断电能力。底盘在总时长结束前约三秒自动归零、
松扭矩和关闭串口。

## 6. 下一门槛：定位与规划，不立即自动运动

1. 用 `rtabmap.db` 启动 localization-only，会话不映射底盘电机；在两个固定、特征丰富的已建图
   位置确认相机可重新定位，并验证 `map -> odom -> base_link`。
2. 从已重定位状态导出/提供 occupancy grid，启动 Nav2 仅做目标点与路径可视化 dry-run；目标选
   已观测空闲走廊，不选深灰未知区。
3. 只读确认三轮的 wheel velocity/position 单位、符号和稳定性；决定是否把 Gemini IMU 与轮速接入
   连续 `odom -> base_link`。
4. 实现带硬件锁、速度上限、250 ms dead-man 与失败归零的 `/cmd_vel ->` 三轮底盘桥。先零命令/
   架空轮验证。
5. 只有规划、控制桥与现场安全门都通过后，才做一次 0.3–0.5 m、有人在场的自主底盘闭环；到达
   桌边后才能接已有 RGB-D/ACT 抓取模块。
