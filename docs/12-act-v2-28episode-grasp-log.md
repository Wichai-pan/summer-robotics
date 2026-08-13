# 实验记录 12 · 28 条示范 ACT、夹爪反馈与首次稳定搬运

- **日期**：2026-08-13
- **平台**：Roihu GH200 + Jetson Orin Nano Super + 白臂 + Gemini 335 + 白臂腕部相机
- **任务**：固定桌面、固定相机视角下，将浅蓝面霜从抓取点拿起、向左短距离搬移并放下。
- **结论**：✅ 28 条示范训练出的第二个 ACT checkpoint 已在 Jetson 完成实时双相机、实时关节状态和物理执行；现场操作者在 10 s、20 s 与约 30 s 试验中均观察到抓起，较长试验完成抓起、左移和放下。⚠️ 这仍是固定场景的现场重复观察，不是严格成功率；30 s 结束时机械臂尚未完全收拢，且有轻微再向前探的尾段动作。

## 1. 早间：夹爪反馈与外部抓取监督器

当天先完成白臂 ID 6（夹爪）的开合、空夹和夹住面霜采样。读取的是伺服的 `Present_Position`、`Present_Velocity`、`Present_Load` 与 `Present_Current`；其中 Load 是控制输出占空比而不是牛顿力，Current 的 raw 值按 STS3215 约为 `6.5 mA/raw`。

已观察到的典型范围：

| 状态 | 位置/现象 | Load | Current raw | 用途 |
|---|---|---:|---:|---|
| 空夹闭合 | 能闭合至低位置，无物体 | 约 2.4–2.8% | 0–1 | 空抓基线 |
| 正确夹住面霜 | 面霜可悬空保持 | 约 26.8–28.8% | 33–37 | 实抓证据 |

因此 rollout 中加入了**外部 side-channel supervisor**：它不改变 ACT 的六维输入或重训 checkpoint，只在 ACT 请求闭合时读取夹爪反馈；位置、负载与电流连续满足阈值后，保持当前夹爪位置，直到 ACT 明确请求释放。它不是“自动评判整次任务成功”的终止器，也不会替代 ACT 的手臂轨迹。

本轮 600-step 运行的终端证据：

```text
GRASP_CONTACT_LATCHED
present_position = 14.85
load_abs_percent = 18.4
current_raw = 16

GRASP_CONTACT_RELEASED
present_position = 15.25
load_abs_percent = 6.8
current_raw = 2
```

该实际抓取的反馈低于上述“典型正确夹住”样本，但仍超过当前保守阈值（Load ≥15%、Current ≥15），并且现场观察到随后完成搬移和放下。后续仍需保存更多实抓/空抓样本，不能把这一条作为最终固定阈值证明。

## 2. 第二版数据与训练

原始 11 条 corpus 和原 checkpoint 均保留不覆盖。Jetson 上录制完成后，建立了不可变的第二版数据副本：

```text
Jetson dataset: /home/jetsonl7/robot-data/act/fixed_pick_place_v1
v2 snapshot:    /scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep
episodes:        28
frames:          19,309
control FPS:     20
```

Roihu 训练使用 episode `0–23`（24 条、17,222 frames）；最后 `24–27` 四条作为未参与训练的时间顺序留出集。训练任务与产物：

```text
Slurm job: 616995 (COMPLETED, 00:06:18)
GPU:       one GH200, gpularge
policy:    official LeRobot ACT
steps:     6,000
checkpoint (Roihu):
  /scratch/project_2016517/panh/summer-robotics-act/outputs/
  act_fixed_pick_place_v2_28ep_616995/checkpoints/006000/pretrained_model
checkpoint (Jetson deployment):
  /home/jetsonl7/robot-data/models/
  act_fixed_pick_place_v2_28ep_616995_006000
```

模型保留原来的输入输出契约：Gemini RGB 640×480、白臂腕部 RGB 640×480、白臂六维状态，输出四个位置关节、wrist-roll 速度和夹爪位置。训练调用 LeRobot 自带的 ACT，并非自行实现的网络。

## 3. 未训练帧离线核验

在四条留出 episode 的起点/中点/终点共 12 帧上，以 GPU 只读推理得到：

| 输出维度 | MAE | 最大绝对误差 |
|---|---:|---:|
| shoulder pan | 1.39° | 3.40° |
| shoulder lift | 1.87° | 4.59° |
| elbow flex | 3.73° | 6.85° |
| wrist flex | 1.06° | 1.86° |
| wrist roll velocity | 0.0023°/s | 0.0044°/s |
| gripper | 4.59 | 15.72 |

预测在 12 帧中有少数 elbow/wrist/gripper 值轻微越出训练范围；Jetson rollout 仍会实施训练范围、单周期 slew、跟踪包络和总行程限制。这是一个小型、时间顺序留出检查，不是随机泛化评估，也不能凭该表推断物理抓取成功率。

## 4. Jetson 实时预检与物理 rollout

新 checkpoint 在真实 Gemini、真实白腕相机及 torque-free 白臂读数下的预检通过：

```text
status = PASS
cameras = true
serial_read_only = true
torque_enabled = false
motion_command_sent = false
all live joint values within training min/max = true
```

随后在现场人员清空工作区、每次显式确认 `ROLLOUT`、并可立即切断 12V 的条件下运行。固定执行保护为 20 FPS、手臂每周期最多 1.5°、夹爪最多 3 units、总手臂行程 100°、肘部总行程 130°、夹爪总行程 60。

| 时长 | 步数 | 现场观察 | 状态 |
|---:|---:|---|---|
| 10 s | 200 | 能到达并抓到面霜 | 操作者报告成功抓起 |
| 20 s | 400 | 能抓起，并继续向左搬移 | 操作者报告抓起 |
| 约 30 s | 600 | 抓起、向左搬移、放下基本完成；回收未完全结束，末尾又轻微向前 | `status=PASS`，600/600 steps |

600-step 运行的末态仍是活动姿态（例如 `elbow_flex≈40.7°`，而不是固定收拢位）。这解释了“放下后没有完全收回、又微探”的表象：ACT 是从示范学习的连续 action chunks，没有任务完成/成功状态或强制终点控制；到第 600 步时它只是在执行最后一段策略序列。该行为不是串口、相机或模型崩溃。

本轮直接使用的核心命令：

```bash
cd /home/jetsonl7/robot-data/tmp/gripper-feedback-smoke

./scripts/jetson_robot_exec.sh \
  --gemini --wrist-a --white --interactive -- \
  python3 tools/act_white_short_rollout.py \
  --checkpoint /data/models/act_fixed_pick_place_v2_28ep_616995_006000 \
  --dataset-root /data/act/fixed_pick_place_v1 \
  --steps 600 \
  --max-arm-step-deg 1.5 \
  --max-gripper-step 3 \
  --max-total-arm-travel-deg 100 \
  --max-total-elbow-travel-deg 130 \
  --max-total-gripper-travel 60 \
  --grasp-supervisor \
  --execute
```

## 5. 明日的可验证下一步

1. 用同一物体位置、光照、云台抓取视角和收拢起点，做至少 5 次标准化 600-step 试验；每次保存时间戳日志和 `SUCCESS / PARTIAL / FAIL` 标签。
2. 对每次试验额外标记：第一次闭合是否夹中、是否触发 contact latch、是否完成放下、是否回到固定终点、是否发生回探。
3. 将 supervisor 的“夹住后保持”与腕部 RGB 的抬升后视觉确认接起来；失败时最多一次重试，成功放下后使用确定性 return-to-folded，而不是继续让 ACT 生成后续动作。
4. 录制更多干净的完整示范（尤其抓取/放下/回收末段），再决定是否用更大数据集训练第三个 checkpoint。

模型、视频、原始 dataset、校准缓存和现场原始日志均留在 Jetson/Roihu 机器状态中，不进入 Git；Git 只记录可复现的脚本、配置与本实验日志。

### 日志说明

本轮 200/400/600-step 命令是直接运行 `act_white_short_rollout.py`，因此没有自动写入
`/home/jetsonl7/robot-data/logs/` 的时间戳文件；本记录中的现场结果来自操作者在同一实验会话的观察，600-step 终端输出作为可追溯执行证据。明日的标准化重复试验应统一走
`scripts/jetson_act_trial.sh`（更新其 checkpoint 后）或为 v2 提供同等的日志入口，以避免再次出现“运行成功但缺少独立日志文件”的问题。
