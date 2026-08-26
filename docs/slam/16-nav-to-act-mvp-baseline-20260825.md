# Nav2 到 ACT 抓取放置 MVP 基线（2026-08-25）

## 结论

本日确认了当前项目的最低端到端基线：在固定、已建图的室内场景中，机器人可从已知起点完成 RGB-D 重定位与受监督底盘导航到桌边，再将 Gemini 从建图位切换到 ACT 抓取位，运行固定场景的 ACT 抓取/局部放置 rollout，最后安全收拢白臂。该结论表示各模块已有一次可串联的工作流；它不表示抓取已稳定、地图可在任意改变后的房间复用，或机器人已能携物导航到第二个目标。

## 当天实施的集成入口

新增的 `scripts/jetson_nav_then_act_pick_place.sh` 保持了旧的单模块脚本，按下列顺序仅作编排：

1. 黑板 ID7/8 Gemini 回到建图固定姿态；
2. 使用 `/data/slam/mapping/20260825T131710Z/rtabmap.db`、桌边目标
   `(0.052, -0.357, -90 degrees)` 进行 Nav2 规划与受监督 docking；
3. Gemini 回到 `/data/config/gemini_gimbal_grasp_pose_v1.json` 的 ACT 固定姿态；
4. 调用既有 `scripts/jetson_act_trial.sh`，默认运行较新的
   `/data/models/act_fixed_pick_place_v2_28ep_616995_006000`、600 steps。

它保留了 `PIPELINE`、`RETURN`、`PLAN`、`MOVE` 和 `READY` 人工确认。任何子阶段失败都会由 `set -euo pipefail` 停住，因而不会在导航失败后错误地进入云台切换或 ACT。首次发布的直接执行方式与旧脚本权限不兼容；commit `53a14b9` 已将编排脚本改为显式 `bash` 调用旧导航和 ACT 入口。Jetson 已在该提交完成 `--help` 无硬件检查。

## 已确认实验与工件

| 项目 | 已确认结果 | 工件/证据 |
| --- | --- | --- |
| Gemini 建图位恢复 | 成功；黑板 ID7/8 回到 map reference 后扭矩释放。 | pipeline 终端记录；mapping reference `/data/config/gemini_gimbal_mapping_down_20deg_v1.json` |
| 管线定位与规划 | 一次管线运行在起点约 `(0.102, 0.039, -93.8 degrees)` 规划到桌边，路径长度 0.449 m。 | `/data/slam/nav2-supervised-execute/20260825T173237Z/`（容器内路径） |
| ID9 使能失败的安全退出 | 此次 `MOVE` 后 ID9 出现 `communication=-6`，未产生运动采样；主动刹车和最终三轮 `goal=0`、`torque=0`、速度归零均已复核。 | 同上 `nav2-execution-report.json` |
| 底盘总线/停机门槛 | 本日先前的只读 cadence 与零速停机复核均通过；它们是开始受监督导航前的硬件门槛，不等同于永不发生瞬时通信失败。 | `/data/slam/base-bus-cadence/20260823-base-bus-01.json`、`20260823-base-bus-02.json`；`/data/slam/base-shutdown-sequence/20260823-stop-01.json` |
| ACT 固定场景 rollout | 最新可追溯 ACT run 使用 28-epoch checkpoint、600 steps；rollout 和最终收拢均报告 `PASS`，但操作员标注 `PARTIAL`，原因“夹爪张开太晚”。 | `/home/jetsonl7/robot-data/logs/20260825_204213_table_pick_place_01.log` |
| 端到端 MVP 现场观察 | 操作员报告：一次串联测试到达桌边位置总体良好，抓爪仍有不稳定。此为现场观察；未把它量化为成功率。 | 当日操作员记录；应在后续 run 以唯一 label 和时间戳补充导航/ACT 工件配对。 |

## 当前边界与下一步

- **已完成的最低基线**：固定地图、固定桌边目标、人工确认下的导航后 ACT 抓取/局部放置。
- **主要未完成项**：ACT 抓爪时机/物体位置对齐不稳定；ID9 白板通信仍可能瞬时失败；地图与定位只应在当前固定场景、已观测区域使用。
- **下一次实验顺序**：先跑只读总线 cadence 和零速停机检查；通过后用唯一 `--label` 运行完整管线，并保存相同时间窗口下的导航目录与 ACT 日志。若 Nav2 失败，停止而不进入 ACT；若 ACT 标记 `PARTIAL/FAIL`，保留日志并单独复核物体初始位置、抓取视角和夹爪反馈，而不修改已通过的导航安全参数。

