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

> 当前状态：机器人本体已组装；Jetson / Quest / 电池未拆封。

## 算力架构（三段，别混）

| 阶段 | 在哪算 | 干什么 |
|---|---|---|
| 开发 | **Mac / Windows**（USB 直连双臂） | 标定 · 遥操作 · 采数据 |
| 训练 | **学校 V100 / 集群** | 离线训练 ACT 策略 |
| 部署 | **Jetson**（机器人上） | 实时推理 · 自主控制 |

V100 只做**离线训练**；**实时控制必须在本地**（Mac/Windows 有线 / Jetson），不能走远程集群（延迟会毁掉控制环路）。开发脚本 `tools/*.py` 跨平台（Mac/Windows/Linux 自动按板序列号找端口，见 [docs/01 §10](docs/01-setup-and-first-arm-move.md)）。

## 当前阶段 & 下一步

平台上手期。目标：**7.4 第一次 check-up 前跑通完整闭环** —— 机械臂自主完成一次「抓方块 → 放到指定点」。

1. Mac 装 LeRobot → 找串口 → 标定双臂 → 键盘遥操作
2. 接相机录一小段示范数据
3. V100 训 ACT → 部署测试

> 业务场景（养老 / 桌面整理 / 垃圾分拣 / 药品识别提醒…）暂不锁定。先把闭环跑通，**换场景 = 换数据**。打法：窄任务 + 稳 demo + 硬付费方 + 营销视频。

## 链接

- 活动页：https://luma.com/yyushsqi
- XLeRobot 文档：https://xlerobot.readthedocs.io/en/latest/
- XLeRobot 中文 README：https://github.com/Vector-Wangel/XLeRobot/blob/main/README_CN.md
- LeRobot：https://github.com/huggingface/lerobot
