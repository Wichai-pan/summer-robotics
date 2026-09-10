# ForestBridge 队友交接入口（2026-09-10）

这份文件是当前交接的首页。它区分 Git 源代码、Jetson 现场状态、训练产物和公网
部署，避免把“文件在机器上”误认为“已经进入 Git”，也避免把程序 `PASS` 误写成
真实抓取或送达成功。

## 一句话状态

我们的独立工作已整理到 GitHub 分支 `smolvla-longrun`；网页 dry-run 闭环、真实硬件
适配器、共享 Gemini broker 和 SmolVLA 现场执行器都有代码与文档。真实网页运动仍被
安全锁定，必须先由现场队友把当前 9 月地图/工作位定义成新的固定 preset 并验收。

## 权威位置

| 内容 | 权威位置 | 当前状态 |
| --- | --- | --- |
| 本次源代码和交接文档 | GitHub `Wichai-pan/summer-robotics` 的 `smolvla-longrun` 分支 | 已提交；应从这里合入 |
| 本机开发副本 | `/Users/huataipan/Wichai/Hackathons/summer-robotics` | 与上述分支同步后用于继续整理 |
| Jetson 部署克隆 | `/home/jetsonl7/summer-robotics-deploy` | 队友工作树很脏；不是本次提交的同步目标 |
| Jetson 实验数据/日志 | `/home/jetsonl7/robot-data`（容器内通常映射为 `/data`） | 不进 Git；保留原始实验产物 |
| SmolVLA 训练记录 | Roihu 路径和 Slurm job ID 见 SmolVLA 文档 | checkpoint 已复制到 Jetson |
| 公网 Relay | Frankfurt `/data/projects/forestbridge-relay` | 运行中，但目录本身不是 Git 工作树 |

GitHub 分支入口：

```text
https://github.com/Wichai-pan/summer-robotics/tree/smolvla-longrun
```

## 建议阅读顺序

1. `docs/ops/team-handoff-20260910.md`：先了解代码和机器分别在哪里。
2. `docs/ops/web-to-jetson-worker-handoff-20260910.md`：网页到机器人任务闭环、测试和剩余阻塞。
3. `docs/ops/gemini-rgbd-broker.md`：网页、SLAM/Nav2、ACT/SmolVLA 如何共享深度摄像头。
4. `docs/experiments/smolvla-onsite-handoff-20260908.md`：现场 SmolVLA 测试顺序、缓存、保护和模型边界。
5. `docs/experiments/smolvla-handoff-20260908.md`：Roihu 训练、评估、Jetson 延迟和方法限制。
6. `docs/19-machine-handoff-20260830.md`：此前 Nav2→ACT baseline 和机器安全操作。
7. `docs/ops/current-status.md`：长时间线和最新工作状态。

## 本轮独立提交

以下提交按时间顺序位于 `smolvla-longrun`，方便审阅或挑选：

| 提交 | 内容 |
| --- | --- |
| `b93a85b` 及其后续 SmolVLA 提交 | 训练、评估、Jetson 延迟、相机键映射和旧数据 baseline |
| `0b90a96` | 网页/Relay 到 Jetson worker；双白名单、Stop、一次性现场授权和 fail-closed 真实适配层 |
| `57e9ddb` | Gemini 常驻 RGB-D broker；网页、SLAM/Nav2 和策略共享一份相机流 |
| `f82514b` | SmolVLA 离线缓存、白臂保护执行器、只读校准审计和现场实验说明 |

不要只复制单个 Python 文件到 Jetson。脚本、工具、测试和文档是一个整体，并且 broker
提交会修改现场队友也在修改的 `jetson_robot_exec.sh`、任务 guard 和 SLAM wrapper。

## 2026-09-10 实测的 Jetson Git 状态

- 分支：`codex/pick-hold-place-segment-recorder`
- HEAD：`f883962`
- 对应已发布队友分支：`origin/codex/single-arm-pick-hold-place-segment-recorder`
- 工作树：大量已修改和未跟踪内容，包括 VR/TeleGrip、9 月家庭导航、地图、机械臂
  标定、录制脚本和实验 artifacts。

因此本次**没有**在 Jetson 上执行 pull、switch、reset、clean 或覆盖复制。现场队友应先
把自己的代码提交并推到自己的分支；大型地图、虚拟环境、图片、tar 和日志应放在
`robot-data` 或 artifact 存储，不要为了清空状态而盲目全部加入 Git。

推荐整合步骤：

```bash
git fetch origin
git log --oneline origin/smolvla-longrun -12
git show --stat 0b90a96
git show --stat 57e9ddb
git show --stat f82514b
```

然后在干净 clone/worktree 中把 `origin/smolvla-longrun` 合入队友分支，或按需
cherry-pick 上述独立提交。遇到相同文件的真实冲突时人工整合并重跑测试；不要在当前
Jetson 脏工作树里强行合并。

## 已经完成并可交接的能力

- 旧 ACT 固定场景的建图、定位、Nav2 停靠、抓取/放置 baseline 和一键现场管线；
- Roihu 上用旧 ACT 数据训练 SmolVLA，checkpoint、held-out MAE 和 Jetson 延迟记录；
- Jetson 上 SmolVLA 20-step 真实保护执行链验证；这不等于抓取成功；
- 持久化 Hugging Face 基座缓存，正常 rollout 不再每次下载约 2 GB；
- Gemini 常驻 broker，网页监看与正常任务能够读取同一份 RGB-D 来源；
- 网页→Relay→dry-run worker 的完整认证任务闭环；
- 固定白名单硬件适配器、Relay Stop、断线终止和现场一次性 arming 边界。

## 尚未完成，不能在演示中这样宣称

- 网页按钮尚未在当前 9 月地图上真实驱动完整机器人任务；
- 旧 `table_pick_place_01` 与当前家庭地图语义不一致，仍被 motion-lock；
- 还没有完整的“拿药/水→持续保持→底盘到另一工作位→交付”状态机；
- SmolVLA 当前模型只学过旧固定面霜场景，不能声称泛化到药瓶、水瓶或自然语言；
- `PASS` 只证明程序和保护退出，不证明物体真的被夹住或送达；
- `OBJECT_HELD` / `DELIVERED` 还缺经过现场标定的夹爪和腕部视觉验收。

## 日志和产物在哪里

Git 中的文字记录：

- `docs/experiments/`：训练、评估、实验结果与限制；
- `docs/slam/`：建图、定位、导航与工作位；
- `docs/ops/`：服务器、相机 broker、网页闭环与当前状态；
- `docs/19-machine-handoff-20260830.md`：机器交接基线。

Jetson 上不进入 Git 的原始记录：

- `/home/jetsonl7/robot-data/logs/`：ACT、SmolVLA 和脚本终端日志；
- `/home/jetsonl7/robot-data/slam/`：RTAB-Map/Nav2 运行产物；
- `/home/jetsonl7/robot-data/relay-worker/`：网页 worker 的任务事件和控制台日志；
- `/home/jetsonl7/robot-data/services/forestbridge-gemini-broker/`：broker 运行日志和部署副本；
- `/home/jetsonl7/robot-data/models/`：ACT/SmolVLA checkpoint；
- `/home/jetsonl7/robot-data/cache/huggingface/`：SmolVLA 基座模型缓存。

不要把密码、Relay token、SSH 私钥或现场 `.env` 放入 Git。大型数据库、checkpoint、
视频和虚拟环境也不要直接提交；文档中保留路径、job ID、校验和与生成步骤即可。

## 队友最短下一步

1. 先把 Jetson 现有现场代码提交到队友分支，并把大文件移出源码管理范围。
2. 在干净工作树中审阅并合入 `smolvla-longrun`。
3. 用 9 月地图定义新的 `bring_medicine_demo_01`，同步更新 Relay 与 Jetson 两端白名单。
4. 依次做无电机测试、planner-only、现场短程测试；最后才解除 motion lock。
5. 有人持续守住 12 V cutoff 时，验证网页开始、状态回传、Stop、抓取保持和送达判断。

完成第 3–5 步之前，演示视频可以使用已经录好的导航与抓取镜头，但不要标注为当前网页
端到端自主送达。
