# ForestBridge 机器交接记录（2026-08-30）

## 交接结论

当前最低可交付基线已经跑通：Gemini RGB-D 手推建图、旧图重定位、Nav2
规划、三轮底盘停靠、Gemini 云台切换、白臂 ACT 固定物体抓取/局部放置，
以及动作结束后的自动收臂。`scripts/jetson_nav_then_act_pick_place.sh
--auto-demo` 将这些既有模块串联起来；现场操作员只在开始时输入一次
`AUTO_PIPELINE`，其余 `RETURN/PLAN/MOVE/READY/ROLLOUT` 不再暂停流程。
这是一套固定房间、固定桌边目标、固定面霜和固定摆放范围的 Demo 基线，
不是通用家庭机器人，也不代表抓取已经稳定。

## 代码、机器与数据位置

- GitHub source of truth：`origin/main`。
- 队友分支 `origin/yuan` 在交接时指向 `99a9d40`，包含
  `sim_to_real/` 下的 fake-target pick workflow baseline；该分支尚未合入
  `main`。接手者应先独立阅读和测试，再按需要 cherry-pick/合并，不能把它
  当成当前现场 Demo 已验证的一部分。
- Mac 工作区：`/Users/huataipan/Wichai/Hackathons/summer-robotics`。
- Jetson 正式部署目录：`/home/jetsonl7/summer-robotics-deploy`。
- 2026-08-30 现场实验使用的临时工作树：
  `/home/jetsonl7/robot-data/tmp/nav2-rotation-guard-20260822`。该目录当时是
  detached HEAD 加未提交部署改动，只应作为实验现场，不应继续作为代码源。
- 持久实验数据：`/home/jetsonl7/robot-data/`；容器内对应 `/data/`。
- ACT 日志：`/home/jetsonl7/robot-data/logs/`。
- 当前地图：`/data/slam/mapping/20260830T095346Z/rtabmap.db`。
- 当前 ACT checkpoint：
  `/data/models/act_fixed_pick_place_v2_28ep_616995_006000`。
- 建图云台参考：
  `/data/config/gemini_gimbal_mapping_down_20deg_v1.json`。
- 抓取云台参考：`/data/config/gemini_gimbal_grasp_pose_v1.json`。

## 2026-08-30 地图与定位证据

手推建图 `20260830T095346Z` 运行 299.8 s、RGB-D VO 路径 9.68 m，频率
7.98 Hz，tracking loss 为 0。操作员保持机器人朝地图 `-Y` 方向，依次在
起点、中段、桌边做三次相互独立的相机重定位，得到：

| 实际位置 | 地图位姿 `(x, y, yaw)` |
| --- | --- |
| 起点 | `(0.083, 0.066, -90.3°)` |
| 中段 | `(0.078, -0.115, -88.7°)` |
| 桌边 | `(0.060, -0.372, -86.5°)` |

约 43.9 cm 的单调 `-Y` 位移与现场路线一致。Demo 固定目标因此设为
`(0.060, -0.372, -90°)`。本地可查看的地图、质量报告和 planner overlay
保存在 `artifacts/slam/20260830T095346Z/` 与
`artifacts/slam/20260830T101938Z/`。地图中只允许在中央连通的浅色已观测区
选点；孤立区域和灰色未知区不可作为目标。

## 自动导航与管线实验

下表来自 Jetson 的 `nav2-execution-report.json`，不是目测估计：

| 工件目录 | 规划长度 | 结果 | 关键结论 |
| --- | ---: | --- | --- |
| `20260830T110413Z` | 0.477 m | FAIL | 9 号轮使能时单次 `communication=-7`；0 个运动采样；停机读回通过。随后加入幂等扭矩使能的 3 次有限重试。 |
| `20260830T111311Z` | 0.477 m | FAIL | 50 s 超时；结束时仅距目标 4.3 cm、yaw 误差约 2°，实物已到桌边。原 2.5 cm 门槛不符合该固定停靠的可达精度。 |
| `20260830T112023Z` | 0.477 m | PASS | 38.658 s 到达，位置误差 4.62 cm，yaw 误差 4.06°。 |
| `20260830T112909Z` | 0.461 m | PASS | 44.866 s 到达，位置误差 4.84 cm，yaw 误差 2.03°。 |
| `20260830T114235Z` | 0.725 m | PASS | 57.083 s 到达，位置误差 4.75 cm，yaw 误差 5.96°。 |
| `20260830T114727Z` | 0.725 m | PASS | 45.467 s 到达，位置误差 4.90 cm，yaw 误差 5.80°。 |

集成 Demo 默认使用 5 cm 位置容差；独立 Nav2 工具的严格默认没有被放宽。
自动管线在导航前先收拢白臂，随后恢复建图云台、定位/规划/移动、切换到
抓取云台、运行 ACT，最后再次收拢白臂。任何子阶段非零退出都会阻止下一
阶段；底盘错误仍执行主动零速、关闭三个轮子扭矩并读回确认。

`demo_auto_pipeline_03`、`final_demo_recording_01` 和
`final_demo_recording_02` 的 ACT 日志均记录 rollout 程序 PASS，并进入最终
自动收臂且收臂 PASS。自动模式将抓取结果记为 `UNKNOWN`，因此物理抓取是否
成功必须引用现场观察或录像，不能从程序 PASS 推断。

交接前已经完成 Bash 语法检查、Python `py_compile`、前端 JavaScript 语法检查
和 `git diff --check`；Jetson 上此前针对底盘、Nav2 与组合管线的核心测试为
26 passed。新增网页 relay/worker 测试没有在最后一次 Jetson 临时工作树中完整
执行（该工作树缺少新增测试文件），而交接 Mac 环境没有安装 `pytest`。因此
这些网页测试仍应由接手者从正式 `main` clone 中补跑，不能记录为已通过。

## ACT 抓取现状

独立的三次固定桌边试验 `20260830_134305/134535/134710` 分别被操作员标记为
FAIL、SUCCESS、PARTIAL，说明新版 28-episode 模型能完成抓起和放下，但对
面霜位置、纸张、视角和照明仍敏感。后续 placement trials 中至少有一次明确
SUCCESS（`20260830_150413_placement_test_01.log`），但连续测试并未形成稳定
成功率。

两次测试触发了夹爪温度保护：

- `20260830_145221_placement_test_01.log`：68°C；
- `20260830_151006_placement_test_01.log`：67°C。

温度门触发后程序给白腕发送零速度、关闭白臂扭矩并恢复位置模式。此时不会
继续最终收臂，因为继续驱动过热电机不安全。不得提高 60°C 保护门槛；关闭
12 V、支撑松扭矩机械臂并充分冷却后，才能执行回正或下一次 rollout。正式
Demo 应固定最近成功的物体位置并用胶带标记，不要用连续高频试验换取偶然
成功。若后续确实补数据，只收集同一停靠位附近的小范围高质量成功示范，并
保留当前 checkpoint，不从头覆盖训练。

## 新队友首日检查顺序

1. 现场必须有人持有 12 V 断电开关；清空底盘、云台线缆和双臂空间。
2. SSH 登录 Jetson，确认 Tailscale/Wi-Fi、磁盘和容器状态。
3. 检查白板 ID1–9、黑板 ID1–8；若瞬时无响应，先停止所有会话，再重新
   插拔对应控制板电源。禁止同时打开两个硬件容器。
4. 运行只读 bus cadence 和零速/扭矩关闭检查，确认三轮 ID7/8/9。
5. 检查 Gemini 是否处于建图参考位；固定外参会话期间不得移动云台。
6. 用新地图做一次静止重定位，检查起点是否接近上述已验证范围。
7. 先做短导航，再做完整自动管线；不要直接从未知地图区域启动长距离运动。
8. ACT 前检查夹爪已经冷却、物体位于胶带标记位置；两次 rollout 之间留出
   冷却时间。

常用通信检查：

```bash
cd /home/jetsonl7/summer-robotics-deploy

bash scripts/jetson_slam_exec.sh --white --interactive -- \
  python3 tools/scan_servos.py /dev/ttyACM0

bash scripts/jetson_slam_exec.sh --black --interactive -- \
  python3 tools/scan_servos.py /dev/ttyACM1
```

完整自动 Demo：

```bash
cd /home/jetsonl7/summer-robotics-deploy

bash scripts/jetson_nav_then_act_pick_place.sh \
  --auto-demo \
  --database /data/slam/mapping/20260830T095346Z/rtabmap.db \
  --goal-x 0.060 \
  --goal-y -0.372 \
  --goal-yaw-deg -90 \
  --duration 15 \
  --robot-radius-m 0.30 \
  --max-path-m 1.40 \
  --max-runtime-s 80 \
  --max-tracked-travel-m 1.50 \
  --position-tolerance-m 0.050 \
  --dock-entry-distance-m 0.18 \
  --dock-yaw-align-tolerance-deg 6 \
  --control-pose-source wheel \
  --label handoff_demo_01
```

现场只输入一次 `AUTO_PIPELINE`。这不是无人值守授权：12 V 急停必须一直有人
看守。若起点较近，应缩小 `--max-path-m` 和 `--max-tracked-travel-m`，不要把
上限当作目标距离。

## 网页边界

`https://robot.wichai.xyz` 已部署认证页面、任务/事件 relay、Jetson heartbeat
协议和显式开启的低频相机监看。Gemini、白腕和黑腕空闲快照均验证过；任务内
预览复用 SLAM/ACT 已有图像流，不应打开第二个物理相机句柄。公网 worker 当前
仍是 dry-run-only，真实 ROS、串口和电机适配器尚未接入网页任务执行。因此
不能向接手者声称“网页已可远程启动真实机器人”；真实运动仍从 Jetson 现场
终端启动。

## 禁止事项与未完成工作

- 不在无人现场时远程运动；Web Stop 不能替代物理 12 V 断电。
- 不使用 `/dev/videoN` 猜摄像头；使用固定 USB path alias。
- 不绕过 `scripts/jetson_robot_exec.sh` 直接占用相机或串口。
- 不在固定外参建图/定位过程中移动 Gemini 云台。
- 不因 `communication=-6/-7` 或温度保护而删除安全门、增加无限重试或提高
  温度/扭矩限制。
- 不把程序 `PASS` 当作抓取成功；ACT 仍需要录像或操作员标签。
- 下一阶段优先事项：整理正式 Demo 视频；把网页 task worker 接到经过现场
  验证的 allow-listed 管线；随后才考虑补少量针对性 ACT 数据或多物体扩展。
