# 实验记录 10 · ACT 训练结果与 Jetson 推理部署

- **日期**：2026-08-10
- **平台**：Roihu GPU 集群 + Jetson Orin Nano Super
- **数据**：固定场景白臂面霜拿取与放置，Gemini RGB、白臂腕部 RGB、白臂状态与实际发送动作
- **目标**：确认录制数据能够训练 ACT，并把 checkpoint 部署到 Jetson 完成离线与实时相机推理。
- **结果**：✅ Roihu 训练产生 step 6,000 checkpoint；✅ Jetson CUDA 完成 11 帧离线推理；✅ 实时 Gemini + 白臂腕部图像进入 ACT 并产生六维动作；✅ 全程未映射电机串口、未产生物理动作；⚠️ 部分输出略超训练数据范围，尚未批准真实机器人 rollout。

## 1. 数据与训练产物

当前 Jetson 数据集：

```text
/home/jetsonl7/robot-data/act/fixed_pick_place_v1
episodes = 11
frames   = 9563
fps      = 20
```

策略输入：

- `observation.state`：白臂六关节状态；
- `observation.images.gemini_rgb`：640×480 RGB；
- `observation.images.white_wrist_rgb`：640×480 RGB。

策略输出：

- `shoulder_pan.pos`
- `shoulder_lift.pos`
- `elbow_flex.pos`
- `wrist_flex.pos`
- `wrist_roll.vel_deg_s`
- `gripper.pos`

Roihu 训练任务 `572912` 产生 step 6,000 checkpoint。`/projappl` 中的副本仅作为集群长期备份；Jetson 推理不依赖集群，实际读取：

```text
/home/jetsonl7/robot-data/models/act_fixed_pick_place_572912_006000
```

模型和数据集体积较大，均保存在 `/home/jetsonl7/robot-data/`，不提交到 Git。

## 2. Jetson 离线推理门槛

新增 `tools/act_checkpoint_dry_run.py`。该工具加载 checkpoint、LeRobotDataset、归一化器和视频帧，在 CUDA 上输出 ACT 动作，但不打开相机、串口或电机。

单帧命令：

```bash
cd /home/jetsonl7/summer-robotics-deploy

./scripts/jetson_robot_exec.sh -- \
  python3 tools/act_checkpoint_dry_run.py \
  --checkpoint /data/models/act_fixed_pick_place_572912_006000 \
  --dataset-root /data/act/fixed_pick_place_v1 \
  --frame-index 0 \
  --device cuda
```

随后一次加载模型并抽查覆盖数据集的 11 个时间点：

```bash
./scripts/jetson_robot_exec.sh -- \
  python3 tools/act_checkpoint_dry_run.py \
  --checkpoint /data/models/act_fixed_pick_place_572912_006000 \
  --dataset-root /data/act/fixed_pick_place_v1 \
  --frame-indices 0,956,1912,2868,3824,4780,5736,6692,7648,8604,9562 \
  --device cuda
```

结果：

| 动作维度 | MAE | 最大绝对误差 | 超出训练 min/max 次数（11 帧） |
|---|---:|---:|---:|
| shoulder pan | 1.91° | 6.02° | 0 |
| shoulder lift | 0.84° | 2.33° | 1 |
| elbow flex | 4.26° | 12.41° | 3 |
| wrist flex | 1.76° | 4.34° | 4 |
| wrist roll velocity | 0.004°/s | 0.009°/s | 0 |
| gripper | 1.77 | 4.58 | 2 |

这一步证明了以下链路可以在 Jetson 上独立运行：

```text
checkpoint + LeRobotDataset + 双路视频解码
  -> NVIDIA PyTorch 2.8 / CUDA
  -> ACT 六维动作
```

它不是成功率评估。11 个抽样点很少，而且单帧预测与示教动作误差不能代替完整闭环 rollout。

## 3. 实时双相机推理门槛

第二个测试只映射 Gemini 与白臂腕部相机，没有映射 `/dev/ttyACM0` 或 `/dev/ttyACM1`：

```bash
./scripts/jetson_robot_exec.sh \
  --gemini --wrist-a -- \
  python3 tools/act_checkpoint_dry_run.py \
  --checkpoint /data/models/act_fixed_pick_place_572912_006000 \
  --dataset-root /data/act/fixed_pick_place_v1 \
  --frame-index 0 \
  --device cuda \
  --live-cameras \
  --white-wrist-device /dev/wrist-2-4-1 \
  --camera-width 640 \
  --camera-height 480 \
  --camera-fps 30
```

结果：

- Gemini SDK 成功启动；
- 白臂腕部 V4L2 相机成功启动；
- 两张实时 RGB 图像进入 ACT；
- Jetson CUDA 产生有限的六维动作；
- 串口/电机未映射，物理运动不可能发生。

该测试的关节状态仍来自数据集 frame 0，因此只能证明实时视觉接线正确，不能称为完整在线策略。输出中的 `recorded_action_reference_only` 与当前实时画面不对应，不应当作为实时精度指标。

## 4. 当前安全边界

现在可以说“ACT 模型已经在 Jetson 上运行”，但不能说“ACT 已经可以自主抓取”。物理执行前仍缺少：

1. 松扭矩读取白臂实时状态，并复现录制时的 `wrist_roll` 跨圈数值分支；
2. 将实时状态与实时双相机图像共同输入策略；
3. 把每个输出裁剪到可信训练范围，并增加单周期步长和速度限制；
4. 相机陈旧、串口异常、跟踪误差或进程退出时立即停止并松扭矩；
5. 从固定收拢姿态依次验证“只保持姿态”与“一次 1–2° 小动作”；
6. 最后才允许现场监督下的完整 rollout。

腕部特别需要谨慎：固定姿态 JSON 在位置模式下的角度，和录制器切换到速度模式后的连续 wrist state 可能位于不同的数值分支。不能直接把 JSON 的腕部角度送给 ACT。

## 5. 同步状态

本地、GitHub `origin/main` 与 Jetson `/home/jetsonl7/summer-robotics-deploy` 均通过 fast-forward 同步。Git 只保存代码、测试和文档；训练数据、checkpoint、校准缓存与密钥继续作为 Jetson/集群机器状态管理。
