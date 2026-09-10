# SmolVLA 现场实验交接（2026-09-08）

这份文档交给现场队友使用。它只描述已经存在并核验过的能力，不把一次短动作
误写成抓取成功。

## 已经完成的工作

- 旧的 28 条固定场景 ACT 数据已在 Roihu 上训练成 SmolVLA checkpoint。
- checkpoint 已复制到 Jetson：
  `/home/jetsonl7/robot-data/models/smolvla_fixed_pick_place_1097975_020000`。
- `model.safetensors` 大小约 869 MiB，SHA256 为
  `cfafd84c19e723b0e70c055a44273a8e09088a12e185b15d59ab84cad50cad18`。
- Jetson 推理中位数约 1.226 s，低于一个 50-step action chunk 的 2.5 s
  预算；这是速度验证，不是实物抓取成功率。
- Gemini 已改为常驻 broker：网页监看与机器人任务读取同一份图像流，不再各自
  打开深度摄像头。腕部摄像头仍由当前机械臂任务独占。
- 执行器包含逐关节步进/总行程限制、跟踪误差保护、`wrist_roll` 速度语义、
  60°C 温度上限和抓取接触 supervisor。
- 2026-09-08 的 20-step 真机测试执行了约 1 秒并正常结束、松扭矩；期间没有
  检测到夹爪接触（`contact_latched=0`），因此它只证明执行链和保护链工作，
  **不证明已经抓起物体**。

## 不再重复下载模型

训练好的 checkpoint 本来就在 Jetson。此前每次出现约 2.03 GB 下载，是因为
`docker run --rm` 的临时容器没有持久化 Hugging Face 的
`HuggingFaceTB/SmolVLM2-500M-Video-Instruct` 基座缓存。

现在基座缓存固定在：

```text
/home/jetsonl7/robot-data/cache/huggingface
```

缓存已于 2026-09-08 准备完成，revision 为 `7b375e1b73b11138ff12fe22c8f2822d8fe03467`。
只在缓存被删除或明确需要更新基座版本后再次运行（不打开摄像头和电机）：

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_prepare_smolvla_cache.sh
```

正常 rollout 强制使用离线缓存；如果缓存不存在会直接报错并提示上述命令，
不会在现场临时下载。

缓存后的离线加载已经实测：489 组权重从本地读取，日志中没有 Hub 请求警告、
配置下载或模型下载进度。

## 已解决的集成问题：不要覆盖 LeRobot 的校准路径

缓存后的最初两次 dry run 报告白臂六个电机都只有 motor 数据、没有 cached
校准；紧接着的独立差异审计却返回 `PASS`。根因已经查明：最初 wrapper 设置了
`HF_HOME=/data/cache/huggingface`，而 LeRobot 也使用 `HF_HOME` 定位机械臂校准，
因此它看不到原来挂载在 `/root/.cache/huggingface/lerobot/calibration` 的文件。
这不是电机寄存器丢失，也不是队友改坏了机械臂。

现在只设置 `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE` 来重定向模型缓存，不再修改
`HF_HOME`。模型仍从 `/data/cache/huggingface/hub` 离线加载，LeRobot 校准仍使用
原来的只读挂载。当前缓存约 6.7 GiB（包含 Hub/Xet blob 与展开快照），Jetson
剩余空间足够；不要为了省空间在演示前手工删其中的 blob。

执行器现已纳入仓库的 `tools/smolvla_white_rollout.py`，校准预检会以 0.15 秒间隔
最多读取三次；任一次完整匹配即可继续。若三次都失败，它会打印最终的具体关节、
homing/range cached/motor 差异并安全退出，仍然不会写寄存器。

现场队友先运行只读差异检查：

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh --white -- \
  python3 tools/audit_so100_calibration.py
```

它只打印每个关节的 cached/motor 差异，不写寄存器。把完整 JSON 发回项目记录。
不要直接重录校准、不要复制其他机械臂的校准，也不要跳过 `is_calibrated` 检查。
一般不需要每次运行这个审计；它用于 dry run 再次报告校准不匹配时定位问题。
如果审计为 `PASS`，可继续 dry run；如果审计确有差异，应使用团队原先验证过的
白臂校准恢复流程，由现场人员在松扭矩状态下写回并回读验证。在真实差异解决前
不要执行 `--execute`。

## 现场测试顺序

必须有人在机器人旁边持续守住 12 V 急停。确认白臂全程无障碍、物体在训练时的
标记位置、Gemini broker 正常，并在连续试验之间检查夹爪温度。

当前白臂在上一轮 20-step 实验后没有回到收拢位，最新无动作检查显示
`elbow_flex` 相对 folded reference 偏约 `-13.6°`。由现场队友先执行受监督回收：

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh --white --interactive -- \
  python3 tools/return_white_to_folded_pose.py --execute
```

看完打印的回收计划，清空整段机械臂路径并守住 12 V，再输入 `RETURN`。这一步
会真实移动白臂，不能远程无人执行。

1. 先做无电机 dry run；若它报告校准不匹配，再运行上述只读审计：

   ```bash
   cd /home/jetsonl7/summer-robotics-deploy
   bash scripts/jetson_smolvla_white_rollout.sh
   ```

   预期结尾是 `DRY RUN`，且白臂保持松扭矩。

2. 第一次真机只做 20 steps（约 1 秒）：

   ```bash
   bash scripts/jetson_smolvla_white_rollout.sh --execute --steps 20
   ```

   阅读打印的首个预测、限幅原因和最终状态，确认运动方向正确后再增加长度。

3. 分阶段扩大到 100、300、600 steps；每一档都先重新摆好现场并由同一个人
   守急停：

   ```bash
   bash scripts/jetson_smolvla_white_rollout.sh --execute --steps 100
   bash scripts/jetson_smolvla_white_rollout.sh --execute --steps 300
   bash scripts/jetson_smolvla_white_rollout.sh --execute --steps 600
   ```

   不要因为一次程序 `PASS` 就跳到下一档。只有现场确认运动合理、没有碰撞、
   没有过热才继续。`PASS` 表示程序和安全退出完成，不等于抓取成功。

4. 每次人工记录：物体初始位置、steps、是否接触、是否抬起、保持是否滑落、
   是否按预期放下、是否回到安全姿态、温度、终端完整输出。至少分别统计
   `成功 / 近成功 / 失败 / 保护中止`，不要只保留成功视频。

任何异常都立即断 12 V；不要提高 60°C 温度阈值、行程上限或跟踪误差阈值来
“完成”一次实验。

## 当前模型能做什么、不能做什么

这个 checkpoint 学的是旧场景中的“固定位置面霜罐抓起、短距离放下、回收白臂”。
训练集只有一个任务描述。它可以作为执行器和 SmolVLA 训练链路的 baseline，
但不能据此声称会抓药瓶、水瓶、跨房间保持，或理解任意语言指令。

新的演示任务是“从一个工作位拿药瓶或水，底盘移动到另一个工作位，再交给人”。
建议把闭环拆成三段：

1. SmolVLA `pick`：识别指定物体、接近并夹住；
2. 确定性 `hold`：接触 supervisor 锁存夹爪目标，机械臂保持安全携带姿态，
   Nav2 独立移动底盘；不要让 VLA 在整段行驶中不断重新预测夹爪动作；
3. SmolVLA `place/hand-over`：到达后重新观察并放到指定位置或递交。

这样“保持”不是一段需要模型凭记忆持续输出的长动作，而是有负载/电流/位置反馈
的明确机器人状态。若发生滑落或过热，状态机中止底盘并进入恢复流程。

## 换场景后的数据与训练

需要重新采集与新任务一致的数据，至少覆盖：

- 药瓶和水瓶各自的合理位置/朝向变化；
- `pick medicine bottle`、`pick water bottle`、`place/hand over` 等真实不同的
  任务文本；
- 成功夹住后的安全抬起和携带姿态；
- 到达目标工作位后的放置或递交；
- 失败样本单独记录，不能混成成功 episode。

优先把 `pick` 与 `place/hand-over` 录成可独立评估的 episode；底盘导航仍使用
已验证的定位/Nav2 模块。数据上传 Roihu 后，用现有 SmolVLA 环境继续微调，输出
新的、按场景命名的 checkpoint；保留当前 checkpoint 作为不可覆盖的 baseline。

更完整的训练、评估和路径记录见：

- `docs/experiments/smolvla-handoff-20260908.md`
- `docs/experiments/smolvla-longrun-20260907.md`
- `docs/ops/smolvla-jetson-latency-runbook.md`
- `docs/ops/gemini-rgbd-broker.md`
