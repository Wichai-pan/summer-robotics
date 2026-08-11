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

> 当前状态：机器人全部 USB 已迁移到 Jetson，GPU 容器、Gemini RGB-D、两只手腕相机、控制板稳定识别和跨进程硬件锁均已验证；11 条固定场景示教已训练 ACT，checkpoint 已在 Jetson CUDA 上完成真实抓取、短距离搬运和放置。重复试验仍不稳定，下一步加入夹爪电流/负载与腕部视觉构成的抓取反馈监督器。见 [实验记录 08](docs/08-jetson-migration-log.md)、[实验记录 09](docs/09-leader-follower-wrap-safe-log.md)、[实验记录 10](docs/10-act-training-and-jetson-inference-log.md) 与 [实验记录 11](docs/11-act-grasp-feedback-log.md)。

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

固定场景 ACT 已完成从数据采集、Roihu 训练、Jetson CUDA 推理到真实抓取/搬运/放置的端到端链路，但四次重复试验只有一次部分成功。当前重点从“链路是否能运行”转向“如何可靠判断已经夹住”。

1. 标定白臂夹爪空抓、实抓和滑落时的位置、电流与负载
2. 用腕部相机完成抬升后的抓取视觉确认，并嵌入 ACT rollout
3. 限制单轮重试次数，再补录干净示范并评估是否重新训练 ACT

近期实验记录：[01 机械臂与底盘](docs/01-setup-and-first-arm-move.md) · [04 相机验收](docs/04-camera-validation.md) · [05 Jetson 与监督式 LLM 导航](docs/05-jetson-and-supervised-llm-navigation.md) · [06 RGB-D 抓取准备](docs/06-rgbd-grasp-bringup.md) · [07 Jetson 机载部署](docs/07-jetson-deployment.md) · [08 迁移总日志](docs/08-jetson-migration-log.md) · [09 主从臂与腕部跨圈](docs/09-leader-follower-wrap-safe-log.md) · [10 ACT 训练与 Jetson 推理](docs/10-act-training-and-jetson-inference-log.md) · [11 ACT 重复抓取与反馈分析](docs/11-act-grasp-feedback-log.md) · [SLAM 路线与当前记录](docs/slam/README.md)

> 业务场景（养老 / 桌面整理 / 垃圾分拣 / 药品识别提醒…）暂不锁定。先把闭环跑通，**换场景 = 换数据**。打法：窄任务 + 稳 demo + 硬付费方 + 营销视频。

## 链接

- 活动页：https://luma.com/yyushsqi
- XLeRobot 文档：https://xlerobot.readthedocs.io/en/latest/
- XLeRobot 中文 README：https://github.com/Vector-Wangel/XLeRobot/blob/main/README_CN.md
- LeRobot：https://github.com/huggingface/lerobot
