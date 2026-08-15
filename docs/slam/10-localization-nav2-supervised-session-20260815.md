# 2026-08-15：重定位、Nav2 规划与受监督底盘执行记录

## Summary

- 固定低头 Gemini 的已保存 RTAB-Map 数据库成功重载并发布 `map -> base_link`；两次已知摆放位置的操作员目视核对均认为位置合理。
- Nav2 `ComputePathToPose` 能从实时重定位结果规划到已观测自由空间，目标点选取网页可把像素坐标转换为 map-frame `(x, y)`；此阶段不映射白板或发布轮速。
- 一次约 10 cm 的受监督实机导航完成并确认三轮停止；长路径尚未通过。随后两次长路径执行都在运行中出现白板轮 ID 7/8/9 同时 `communication=-6`，其中最近一次退出后 ID 7/8 的停机未确认，因此禁止继续导航，先处理底盘共同供电/总线链路。

## 1. 目的与固定条件

本次目标是把已保存地图接入可重复的 camera-only 重定位和 Nav2 路径规划，并在现场监督下验证第一段真实底盘运动。地图数据库固定为 `/data/slam/mapping/20260814T140025Z/rtabmap.db`；Gemini 云台保持 mapping-down 参考位：黑板 serial `5B3D043224`、ID 7 raw `4066`、ID 8 raw `1924`，参考 JSON 为 `/data/config/gemini_gimbal_mapping_down_20deg_v1.json`。外参配置固定为 `configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml`。整个运行期间不移动云台；没有验证轮编码器里程计或 IMU 融合。

## 2. 新增/更新的操作入口

| 入口 | 作用与硬件边界 |
| --- | --- |
| `scripts/jetson_slam_localization.sh` | 只映射 Gemini 和黑板进行云台参考检查；以只读模式重载数据库，输出 `map -> base_link`、占据栅格和带红点/蓝箭头的 overlay；不映射白板。 |
| `scripts/jetson_slam_nav2_planning_dry_run.sh` | 在上述定位图上启动 map server 与 Nav2 planner，仅请求 `ComputePathToPose`；不启动控制器、不发布轮速。 |
| `tools/make_nav2_goal_picker.py` | 导出目标点选取 HTML；只应在浅色、已观测自由空间点击。 |
| `scripts/jetson_slam_nav2_supervised_execute.sh` | 先规划，再由现场操作员输入 `MOVE`；只允许白板底盘 ID 7/8/9，白臂 ID 1–6 不接收目标。 |
| `tools/nav2_supervised_base_execute.py` | 使用实时 RGB-D `map -> odom -> base_link` 状态跟踪已规划路径，写 execution report，并在退出时尝试零速度、扭矩关闭和寄存器回读。 |
| `tools/base_stop_diagnostic.py` | 单次短前进脉冲与 RGB-D VO/轮子停机回读诊断；不是导航入口。 |

`configs/nav2/planning_dry_run.yaml` 当前只配置 planner 与全局 costmap：`robot_radius=0.30 m`、未知区不允许通行。它没有启动 Nav2 controller server 或行为树导航器。受监督执行器自行实施速度与行程上限。

## 3. 已完成实验与结果

### 3.1 camera-only 重定位与可视化：通过

使用 `jetson_slam_localization.sh` 重载候选地图并导出 overlay。已记录的成功工件包括：

| 工件目录 | 结果 |
| --- | --- |
| `/data/slam/localization/20260815T102620Z` | `PASS localization RGB-D odometry`；输出 map 位置 `(-0.127, 0.053)` m、朝向 `-26.96°`。 |
| `/data/slam/localization/20260815T103435Z` | `PASS localization RGB-D odometry`；输出 map 位置 `(1.603, -0.308)` m、朝向 `-178.42°`。 |

操作员在两处已知物理位置检查 overlay 后认为定位基本正确。该证据只说明候选地图可被重载并用于视觉重定位，不构成厘米级全场定位精度或安全导航证明。

### 3.2 目标点选择与 Nav2 planner-only：通过

目标点 HTML 输出在本机下载目录，可离线打开；点击会生成 map-frame `x/y` 及 planner-only 命令。planner 从实时 `map -> odom -> base_link` 取起点，而不是使用上一次路径或按时间估算位置。对目标 `(0.650, -0.311, 0°)`，曾生成 1.010 m 路径（20260815T164629Z）；后来机器人重定位到不同起点时，同一目标生成 0.688 m 路径（20260815T171802Z），这是正常的起点变化。一次 planner-only 失败不是地图或底盘故障：命令中的 Markdown 星号 `**0.950**` 被原样传给 float 参数，CLI 因非法浮点数退出。

### 3.3 底盘停机与短距离执行：部分通过

`base_stop_diagnostic.py` 的原始 XLeRobot 前进映射为 `0.040 m/s -> {ID7:-452, ID8:0, ID9:+452}`。一次 0.5 s 前进脉冲的操作员尺量位移约 3 cm，RGB-D VO 起终点净位移约 2.7 cm，且轮子零速/扭矩回读确认。这说明原始轮速映射与短程 VO 量级相符。此前试验过把轮速再除以 50 的换算，现场表现为异常慢速；该方案不应使用。

受监督 Nav2 一次短路径报告 `/data/slam/nav2-supervised-execute/20260815T153539Z/nav2-execution-report.json` 返回 `PASS goal_position_and_yaw_reached`，有 33 个样本并确认停机；操作员观察为约 10 cm 的直线移动。它是首次真实路径跟踪的正向证据，但不足以证明更远路线可靠。

### 3.4 中距离与长距离执行：未通过，存在安全阻塞

| 工件目录 | 路径/观测 | 退出结果 |
| --- | --- | --- |
| `/data/slam/nav2-supervised-execute/20260815T165259Z` | 规划 0.511 m；110 个实时样本中，VO 估计到目标距离从 0.494 m 降至 0.340 m，净位移约 15.5 cm，之后主要转向而未持续前进。 | `FAIL no meaningful goal-distance progress within timeout`；三轮一度 `communication=-6`，停止回读未确认。 |
| `/data/slam/nav2-supervised-execute/20260815T171802Z` | 规划 0.688 m 到 `(0.650, -0.311, 0°)`；只记录 25 个样本后失败。 | 三轮 ID 7/8/9 同时 `communication=-6`。退出尝试中 ID 7/8 仍为 `torque_enable=1`、存在负速度读数，ID 9 扭矩为 0；`stop_readback_confirmed=false`。现场必须使用 12 V cutoff。 |

事后只读扫描恢复到 IDs 1–9，并不推翻上述失败：它只能证明静态通信恢复，不能证明带载运行时可可靠收发停止命令。Jetson 内核日志在对应窗口没有记录 USB/`ttyACM0` 重连，因此已知现象是舵机总线通信超时，不足以从软件日志确定是 12 V 瞬降、白板/轮子总线接头松动，还是其他共同链路问题。

## 4. 结论与接管决策

地图、重定位、目标选取和 Nav2 planner 已连通；真实底盘导航没有通过安全门槛。当前不应把“规划路径长度”解释为实际移动距离，也不能把静态扫描通过解释为动态停机可靠。长距离执行入口目前保留 0.04 m/s、12 deg/s、二次 `MOVE` 确认和最大 35 s 限制；路径许可曾临时扩展到 1.10 m 用于本次监督测试，但在底盘通信可靠性恢复前不得再次执行长路径。

## 5. 接下来一周的优先顺序

1. 断开 12 V 后检查并重新压紧：白板 12 V 输入、白板→轮 7、轮 7→轮 8、轮 8→轮 9 的供电/总线线缆；确认运动中线缆不会被拉紧。
2. 上电后连续进行至少三次只读 `scan_servos.py /dev/ttyACM0`，每次确认 IDs 7/8/9 都出现；这不是最终通过条件。
3. 在空旷区域、现场持有 12 V cutoff 的条件下，先重做短脉冲诊断，要求带载期间和退出后都能稳定写入零速度、关闭三轮扭矩并回读确认；任何 `communication=-6` 或停机未确认都停止后续导航。
4. 硬件门槛通过后，先修正/验证 0.511 m 路线上“中途只转向、不继续前进”的进度控制，再复测同一已规划路线；不要先扩大距离。
5. 通过可重复的中距离路线后，才恢复 0.688–1.10 m 的监督执行；轮编码器与 IMU 融合是后续精度改进，不是修复此通信安全问题的前置替代品。

## Reproducibility Notes

代码基线为 `codex/nav2-planning-dryrun` 上的未提交 Nav2/定位改动；实机工件在 Jetson `/data/slam/`，不在 Git。已运行 `py_compile`（Nav2/诊断 Python）和 `bash -n`（新增 shell 入口）；本机没有 `pytest`，且仓库当前没有 Nav2 执行器的单元测试。所有物理实验必须通过 Jetson 硬件锁入口并由现场操作员监督。
