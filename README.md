# Summer Robotics Challenge — 参赛仓库

Robotics Nation 主办的 3 个月具身智能机器人挑战赛。平台：**XLeRobot**（基于 [LeRobot](https://github.com/huggingface/lerobot)）。

> 队名 / 队员：
> Huati Pan
> Yuan Ou
> Jiacheng Wei

## 关键信息

- 主办：Robotics Nation（Aalto / Otaniemi, Espoo, 芬兰）
- 规模：共 8 队，**前 3 名 + 营销奖** 瓜分 **7000€** 奖池
- 评分：demo 效果 · 技术惊艳 · 商业点子 · 投入程度

## 时间线（2026）

| 日期 | 事件 |
|---|---|
| 6.13 | Kickoff，发放机器人 ✅ |
| 7.4 / 7.25 / 8.15 / 9.5 | 进度 check-up（每 3 周，@mailateippi 发视频/照片）|
| **9.13** | **Demo Day**（评审团前展示）|
| 10.30–11.1 | Robotfair（获奖队展出）|

## 硬件（每队 >1500€，借用，损坏需赔）

- XLeRobot 双臂移动平台（SO-101 臂 + RÅSKOG 推车底盘）
- Jetson Orin Nano 8GB —— 板载实时推理
- Meta Quest 3S —— VR 遥操作
- Orbbec Gemini 335 —— 深度相机
- Anker SOLIX C300X —— 电源

> 当前状态：机器人全部 USB 已迁移到 Jetson，GPU 容器、Gemini RGB-D、两只手腕相机、控制板识别和跨进程硬件锁均已验证。固定房间内已完成手推建图、重定位、Nav2 桌边停靠、ACT 抓取/局部放置和自动收臂的一次授权串联 Demo；抓取仍对摆放敏感，且连续运行会触发夹爪温度保护，不能据此声称通用或稳定自主能力。机器移交以 [2026-08-30 完整交接记录](docs/19-machine-handoff-20260830.md) 为入口。

## 算力架构（三段，别混）

| 阶段 | 在哪算 | 干什么 |
|---|---|---|
| 开发 | **Mac / Windows → SSH → Jetson** | 编辑代码 · 发起遥操作 · 查看数据；USB 统一由 Jetson 持有 |
| 训练 | **学校 V100 / 集群** | 离线训练 ACT 策略 |
| 部署 | **Jetson**（机器人上） | 实时推理 · 自主控制 |

V100 只做**离线训练**；实时控制在机器人随车 Jetson 上执行，不能走远程训练集群。开发机通过 SSH 使用 Jetson；所有硬件命令必须经过带全局锁的容器入口。开发脚本 `tools/*.py` 跨平台按板序列号找端口，原 `arm_keyboard.py` 已增加 SSH 终端输入后端。

## 获取上游依赖

`external/` 包含 LeRobot、XLeRobot 和按平台下载的 SDK，体积较大，不再提交到本仓库。首次 clone 后运行：

```bash
bash scripts/bootstrap_external.sh
```

脚本按文件内声明的 commit 获取两套上游源码，并验证已有 checkout 是否仍在同一个 commit；它不会覆盖或 reset 本机修改。Jetson 镜像构建依赖 `external/lerobot`，因此构建前必须先完成这一步。Orbbec SDK/Viewer 仍需按开发机架构单独下载到 `external/orbbec/`；具体版本与路径见 [相机验收记录](docs/04-camera-validation.md)。

## 当前阶段 & 下一步

固定场景 MVP 已完成从 RGB-D 建图/定位、Nav2 停靠到 ACT 抓取/局部放置和确定性收臂的现场串联。28 条示范的新 checkpoint 能完成抓起、左移与放下，但重复成功率不足，连续高频测试还两次触发夹爪温度保护。当前重点是保全可复现 Demo、完成机器交接，并把程序 PASS 与真实抓取成功严格区分。

1. 用多次空抓、实抓和滑落样本复核白臂夹爪的位置、电流与负载阈值
2. 用腕部相机完成抬升后的抓取视觉确认，并嵌入 ACT rollout
3. 用固定胶带标记复现一次短停靠和一次冷却后的抓取，不做高频碰运气测试
4. 公网任务 worker 仍保持 dry-run-only；真实运动继续由现场终端和 12 V 急停监督

并行启动实验室人机交互路线，但不得绕过上述硬件门槛：第一轮只在独立 worktree 中完成录制视频的
YOLO11n-pose 人体关键点、手势事件、GUI overlay 和自动化 QA，不连接 Jetson、相机、ROS 或电机。
之后按“实时 camera-only → 镜像目标 dry-run → 单臂低速监督镜像 → 大模型白名单技能编排”逐阶段验收；
详见 [13 轻量实验室人机交互路线](docs/13-lab-human-interaction-roadmap.md)。

近期入口：[2026-08-30 机器交接](docs/19-machine-handoff-20260830.md) · [Demo 交付计划](docs/17-demo-delivery-plan-20260827.md) · [网页 relay dry-run](docs/18-web-relay-dry-run-20260827.md) · [ACT v2 抓取](docs/12-act-v2-28episode-grasp-log.md) · [Nav2-to-ACT 基线](docs/slam/16-nav-to-act-mvp-baseline-20260825.md) · [SLAM 路线与当前记录](docs/slam/README.md)

> 目标场景现定义为受监督的化学/生物实验室助手机器人：人员与实验品隔离，通过语言、手势、镜像示教和已验证技能完成任务。近期仍坚持“窄任务 + 稳 demo”，不得把场景愿景当作未经验证的自主能力。

## 链接

- 活动页：https://luma.com/yyushsqi
- XLeRobot 文档：https://xlerobot.readthedocs.io/en/latest/
- XLeRobot 中文 README：https://github.com/Vector-Wangel/XLeRobot/blob/main/README_CN.md
- LeRobot：https://github.com/huggingface/lerobot
