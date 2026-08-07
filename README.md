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

> 当前状态：机器人本体、Gemini 335、两只手腕相机、Jetson、双臂与底盘均已完成首轮连通/控制验收；Gemini→YOLO→RGB-D→人工双确认底盘动作的 MVP 链路已实测。见 [实验记录 05](docs/05-jetson-and-supervised-llm-navigation.md)。

## 算力架构（三段，别混）

| 阶段 | 在哪算 | 干什么 |
|---|---|---|
| 开发 | **Mac / Windows**（USB 直连双臂） | 标定 · 遥操作 · 采数据 |
| 训练 | **学校 V100 / 集群** | 离线训练 ACT 策略 |
| 部署 | **Jetson**（机器人上） | 实时推理 · 自主控制 |

V100 只做**离线训练**；**实时控制必须在本地**（Mac/Windows 有线 / Jetson），不能走远程集群（延迟会毁掉控制环路）。开发脚本 `tools/*.py` 跨平台（Mac/Windows/Linux 自动按板序列号找端口，见 [docs/01 §10](docs/01-setup-and-first-arm-move.md)）。

## 当前阶段 & 下一步

平台上手期。已完成相机、双臂、底盘、实时深度检查点，以及安全监督式的 LLM 目标接近闭环；Gemini RGB-D 对浅蓝桌面物体定位和黑臂人工抓取也已分别验证。下一阶段转向相机到机械臂标定、遥操作数据采集与抓取策略训练。

1. 规划抓取窄任务，确认物体、放置区、相机视角和评价标准
2. 使用双臂遥操作采集一小段抓取示范数据
3. 在 V100 训练 ACT 基线并部署回本地/Jetson 测试

近期实验记录：[01 机械臂与底盘](docs/01-setup-and-first-arm-move.md) · [04 相机验收](docs/04-camera-validation.md) · [05 Jetson 与监督式 LLM 导航](docs/05-jetson-and-supervised-llm-navigation.md) · [06 RGB-D 抓取准备](docs/06-rgbd-grasp-bringup.md) · [07 Jetson 机载部署](docs/07-jetson-deployment.md)

> 业务场景（养老 / 桌面整理 / 垃圾分拣 / 药品识别提醒…）暂不锁定。先把闭环跑通，**换场景 = 换数据**。打法：窄任务 + 稳 demo + 硬付费方 + 营销视频。

## 链接

- 活动页：https://luma.com/yyushsqi
- XLeRobot 文档：https://xlerobot.readthedocs.io/en/latest/
- XLeRobot 中文 README：https://github.com/Vector-Wangel/XLeRobot/blob/main/README_CN.md
- LeRobot：https://github.com/huggingface/lerobot
