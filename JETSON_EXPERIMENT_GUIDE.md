# ForestBridge Jetson 实机实验指南

> 更新日期：2026-08-12
> 机器人主机：`jetsonl7-desktop`
> 正式部署目录：`/home/jetsonl7/summer-robotics-deploy`

本文面向所有队员，说明 XLeRobot 当前如何在 Jetson 上运行代码、Docker 与主机目录如何对应、应该在哪里查看或修改文件，以及进行实机实验时必须遵守的协作和安全规则。

## 1. 先记住这三个目录

| Jetson 主机路径 | 作用 | 是否应直接改代码 |
| --- | --- | --- |
| `/home/jetsonl7/summer-robotics-deploy` | 正式 Git 部署仓库；共享代码的默认入口 | 是，改完应提交到分支 |
| `/home/jetsonl7/robot-data` | 数据集、实验输出、模型输出和实验快照 | 通常否；这里主要放数据 |
| `/home/jetsonl7/robot-data/tmp` | 临时 worktree、诊断脚本和一次性实验 | 仅临时调试，验证后合回正式仓库 |

团队日常工作默认从这里开始：

```bash
cd /home/jetsonl7/summer-robotics-deploy
git status --short
```

如果命令或聊天记录里出现 `/data/...`，它是 **Docker 容器内部路径**。在普通 SSH 终端中，应替换成：

```text
/data/...  <=>  /home/jetsonl7/robot-data/...
```

例如容器中的：

```text
/data/experiments/demo/output.json
```

在 Jetson 主机上实际位于：

```text
/home/jetsonl7/robot-data/experiments/demo/output.json
```

## 2. 登录 Jetson

同一局域网可尝试：

```bash
ssh jetsonl7@jetsonl7-desktop.local
```

通过 Tailscale 可使用当前机器地址：

```bash
ssh jetsonl7@100.75.199.31
```

推荐每位队员使用自己的 SSH 公钥。不要把 API key、私钥或账户密码写进仓库、聊天截图或脚本。

登录后先确认：

```bash
hostname
id
pwd
```

预期主机名为 `jetsonl7-desktop`，用户需要在 `docker`、`dialout` 和 `video` 组中才能使用当前部署方式。

## 3. 当前运行架构

Jetson 主机负责：

- Ubuntu、Docker 和 NVIDIA runtime；
- USB 设备节点；
- Git 工作区；
- 持久化数据、标定和模型文件；
- 跨进程硬件锁。

Docker 镜像负责：

- Python 3.12；
- NVIDIA PyTorch 2.8 / CUDA；
- LeRobot；
- Orbbec Python SDK；
- OpenCV、NumPy 和机器人运行依赖。

当前镜像：

```text
forestbridge-xlerobot:jp62
```

不要在 Jetson 主机的 Python 3.10 环境中直接安装通用 PyPI Torch，也不要在容器里用 `pip install torch` 覆盖 NVIDIA 提供的 Jetson GPU 版本。

## 4. 容器不是长期运行的虚拟机

标准命令格式：

```bash
./scripts/jetson_robot_exec.sh [设备参数] -- COMMAND [ARG...]
```

脚本实际上执行一次：

```text
docker run --rm ... forestbridge-xlerobot:jp62 COMMAND
```

含义是：

1. 每次命令启动一个新容器；
2. 后面的 Python 命令在容器内运行；
3. 程序退出后容器自动删除；
4. 挂载目录中的代码和数据会保留；
5. 写在容器临时文件系统、但不在挂载目录里的文件会消失。

每次看到 NVIDIA/PyTorch 的版权信息，通常只是新容器启动，不是报错。

### 4.1 目录挂载

| Jetson 主机 | 容器内 | 说明 |
| --- | --- | --- |
| 启动脚本所在仓库的根目录 | `/workspace` | 当前执行的代码 |
| `/home/jetsonl7/robot-data` | `/data` | 持久化实验数据 |
| `~/.cache/huggingface/lerobot/calibration` | `/root/.cache/huggingface/lerobot/calibration` | 机器人标定；容器内只读 |

最容易犯错的是 `/workspace`：它取决于从哪一份仓库调用启动脚本。

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh -- python3 tools/example.py
```

执行正式部署仓库中的 `tools/example.py`。

```bash
cd /home/jetsonl7/robot-data/tmp/leader-follow-smoke
./scripts/jetson_robot_exec.sh -- python3 tools/example.py
```

执行临时 worktree 中的另一个 `tools/example.py`。两者虽然在容器内都叫 `/workspace/tools/example.py`，但主机来源不同。

### 4.2 临时进入容器 shell

只检查环境、不映射硬件：

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh --interactive -- bash
```

进入后可执行：

```bash
pwd
python3 --version
python3 -c 'import torch; print(torch.__version__, torch.cuda.is_available())'
ls /workspace
ls /data
```

输入 `exit` 离开。一般不需要使用 `docker exec`，因为这些不是长期运行的容器。

## 5. 设备参数

Docker 默认看不到机器人 USB。只把实验需要的设备传进去：

| 参数 | 映射设备 |
| --- | --- |
| `--gemini` | Orbbec Gemini 335 的 USB 和 V4L 节点 |
| `--white` | 白板控制器，USB serial `5B3D040988` |
| `--black` | 黑板控制器，USB serial `5B3D043224` |
| `--ports-readonly` | 两块控制板的只读设备映射 |
| `--wrist-a` | 物理 USB path `2.4.1` 的手腕相机 |
| `--wrist-b` | 物理 USB path `2.4.3` 的手腕相机 |
| `--interactive` | 把当前 SSH TTY 连接给容器，允许读取键盘和确认文本 |

当前常见节点是：

| 设备 | 常见节点 | 稳定识别方式 |
| --- | --- | --- |
| Gemini 335 | `/dev/video0`–`/dev/video7` | USB `2bc5:0800` |
| 两只手腕相机 | `/dev/video8`–`/dev/video11` | 物理 USB path，不依赖 video 编号 |
| 白板 | `/dev/ttyACM0` | serial `5B3D040988` |
| 黑板 | `/dev/ttyACM1` | serial `5B3D043224` |

`/dev/videoN` 和 `/dev/ttyACMN` 在拔插或重启后可能变化。启动脚本按稳定 USB 身份解析，不要在新脚本中假定固定编号。

## 6. 硬件锁与安全边界

所有团队硬件命令必须通过 `jetson_robot_exec.sh`。它持有：

```text
/tmp/forestbridge-xlerobot.lock
```

如果另一位队员正在使用硬件，新命令会拒绝启动。禁止直接运行带硬件的 `docker run`，因为这会绕过锁。

实机运动规则：

1. 必须有现场人员清空运动范围并可以立即切断 12V；
2. 跨国远程队员可以开发、看日志、运行仿真和感知，但不得在没有现场确认的情况下启动电机；
3. 一次只运行一个访问控制板或相机的硬件容器；
4. 方向异常、抖动、碰撞风险或串口报错时立即停止；
5. 不通过删除标定检查、无限放宽关节范围或 `chmod 777` 来绕过问题；
6. 临时测试通过后，应把代码合回正式 Git 分支，不长期依赖 `/robot-data/tmp`。

## 7. 常用检查命令

### 7.1 主机状态

这些命令直接在 Jetson 主机运行，不需要 Docker：

```bash
hostnamectl
cat /etc/nv_tegra_release
df -h
ip -br addr
lsusb
docker images
tailscale status
```

### 7.2 无硬件容器自检

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_container_smoke.sh
```

它检查 Python、LeRobot、PyTorch、CUDA、OpenCV 和 Orbbec 导入，不映射机器人 USB。

### 7.3 控制板身份检查

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_ports_smoke.sh
```

### 7.4 Gemini RGB-D 快照

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_orbbec_smoke.sh 5
```

输出保存在主机：

```text
/home/jetsonl7/robot-data/tmp/
```

### 7.5 黑臂 SSH 键盘控制

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh --interactive --black -- \
  python3 tools/arm_keyboard.py black --terminal
```

出现是否重标定的询问时，除非团队明确安排重新标定，否则输入 `n`。该脚本会移动机械臂，必须现场操作。

### 7.6 Gemini 两轴云台姿态

Gemini 云台使用黑板 ID 7/8。固定视角 IK 和 ACT 实验前，应先恢复到保存的抓取视角；SLAM 可以在其他时间自由转动云台。

只读当前两个原始编码器，不上扭矩、不写寄存器：

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh --black -- \
  python3 tools/gemini_gimbal_pose.py read
```

首次在已确认的固定抓取视角保存基准：

```bash
./scripts/jetson_robot_exec.sh --black -- \
  python3 tools/gemini_gimbal_pose.py save
```

默认保存在主机持久化数据盘：

```text
/home/jetsonl7/robot-data/config/gemini_gimbal_grasp_pose_v1.json
```

容器内对应 `/data/config/gemini_gimbal_grasp_pose_v1.json`。这个文件属于机器状态，不提交 Git；更换控制板、云台结构或相机安装后必须重新保存。

确认 ID 7/8 物理轴映射时，每次只让一个轴低速移动约 3°：

```bash
./scripts/jetson_robot_exec.sh --black --interactive -- \
  python3 tools/gemini_gimbal_pose.py jog --id 7 --degrees 3 --execute
```

程序会先显示最短路径计划，只有输入 `JOG` 才会上该轴扭矩。观察它是左右看还是上下看；再对 ID 8 做同样检查。确认后记录映射，例如：

```bash
./scripts/jetson_robot_exec.sh --black -- \
  python3 tools/gemini_gimbal_pose.py set-axis-map \
  --yaw-id 7 --pitch-id 8 --yaw-positive right --pitch-positive down
```

本机已经现场验证：ID 7 是 yaw，正方向向右；ID 8 是 pitch，正方向低头。因此负方向分别是向左和抬头。更换控制板、舵机方向或拆装云台后需要重新确认。

低速回到抓取视角：

```bash
./scripts/jetson_robot_exec.sh --black --interactive -- \
  python3 tools/gemini_gimbal_pose.py return --execute
```

只有输入 `RETURN` 才会控制 ID 7/8。工具不命令黑臂 ID 1–6；返回采用原始编码器的最短方向、4°/s 默认速度、120° 默认最大行程、0.5° 最终误差，并在结束时零速度、松扭矩和恢复位置模式。目标若超过最大行程会在上扭矩前拒绝。

STS3215 安装 `homing_offset` 后，位置模式与速度模式的 `Present_Position` 数字表示会不同。工具会在松扭矩、零速度状态切换模式，实测每个轴的坐标偏移并同步转换目标；不要把这个数值跳变误认为云台真实旋转。最终复核仍在位置模式下使用保存的原始编码器值。

手动记录左右/上下四个安全端点（程序不会命令云台运动）：

```bash
./scripts/jetson_robot_exec.sh --black --interactive -- \
  python3 tools/calibrate_gemini_gimbal_limits.py
```

输入 `RECORD` 后，ID 7/8 会松扭矩。按提示把云台缓慢摆到左、右、上、下四个位置，每次按 Enter 记录编码器。结果保存在主机 `/home/jetsonl7/robot-data/config/gemini_gimbal_manual_limits_v1.json`，不会写舵机硬限位。完成后运行 `return --execute` 回到固定抓取视角。

原始编码器读数是回归依据。界面显示的 `one-turn` 角度只是 `raw × 360/4096`，不是相对于地面或机器人坐标系标定过的世界 yaw/pitch 角。

## 8. 当前实验代码在哪里

### 8.1 正式共享代码

默认查看：

```bash
cd /home/jetsonl7/summer-robotics-deploy
git status --short
git branch --show-current
git log --oneline -10
find tools scripts docs -maxdepth 2 -type f | sort
```

需要分享给队友、合并或长期维护的代码必须进入这个 Git 仓库及相应分支。

### 8.2 队友 sim-to-real 原版

队友 `simtoreal` 分支的核心原文件是：

```text
sim_to_real/real_pick_blue_cylinder.py
```

曾用于 Jetson 白臂验证的固定实验快照位于主机：

```text
/home/jetsonl7/robot-data/experiments/simtoreal-white-7858c5a/working/sim_to_real/
```

其中：

- `real_pick_blue_cylinder.py`：队友原版快照；
- `real_pick_blue_cylinder_white_smoke.py`：为白臂安全测试派生的副本；
- `pick_config.white_sim_smoke.json`：当次模拟参数 smoke 配置；
- `pick_outputs/`：运行计划和输出。

容器命令中对应路径是：

```text
/data/experiments/simtoreal-white-7858c5a/working/sim_to_real/
```

实验快照没有 `.git`，不能在里面查询分支历史。不要把修改实验快照当成已经更新 GitHub。

### 8.3 黑臂 leader → 白臂 follower 临时实验

当前临时工作区：

```text
/home/jetsonl7/robot-data/tmp/leader-follow-smoke
```

2026-08-09 的临时验证文件：

```text
tools/black_leads_white_smoke.py
tools/wrist_roll_velocity_follow.py
tools/black_leads_white_wrap_safe.py
```

其中旧的 `black_leads_white_smoke.py` 已因腕部位置模式跨越编码器
`4095/0` 的风险锁止，不应继续运行。已验证的替代方案是：

- 肩、肘、腕俯仰和夹爪复制相对启动姿态变化；
- `wrist_roll` 单独使用最短角误差的低速速度闭环；
- 输入 `FOLLOW` 的瞬间定义本次相对零点，不自动做两臂绝对角度对齐；
- 腕部达到累计行程边界时夹紧目标，黑臂返回范围后继续跟随。

验证结束后，这两个安全脚本应进入正式仓库：

```text
tools/wrist_roll_velocity_follow.py
tools/black_leads_white_wrap_safe.py
```

正式同步完成后应从 `/home/jetsonl7/summer-robotics-deploy` 运行，不再把
`/home/jetsonl7/robot-data/tmp/leader-follow-smoke` 当作团队代码源。

## 9. 标定、密钥和模型

这些是机器特有或私密状态，不应提交 Git：

```text
/home/jetsonl7/.cache/huggingface/lerobot/calibration/
/home/jetsonl7/summer-robotics-deploy/agents/llm_navigation/.env
/home/jetsonl7/summer-robotics-deploy/yolo11n.pt
```

标定目录在容器中以只读方式出现：

```text
/root/.cache/huggingface/lerobot/calibration/
```

标定文件名是机器人配置 ID 的一部分，例如 `black_arm.json`、`white_arm.json`。不要只根据文件名替换标定；还要确认它与电机内部的 homing offset 和限位寄存器一致。

## 10. 查看、编辑和运行文件

查看文本：

```bash
less PATH/TO/FILE.py
sed -n '1,220p' PATH/TO/FILE.py
```

编辑文本：

```bash
nano PATH/TO/FILE.py
```

查看权限：

```bash
ls -l PATH/TO/FILE.py
```

Python 文件不一定带可执行位。下面可能得到 `Permission denied`：

```bash
./script.py
```

通常应该使用：

```bash
python3 script.py
```

如果文件属于 `root`，先检查它是不是容器产生的输出。只修复明确目标的所有者，不要对整个系统或仓库执行 `chmod -R 777`。

## 11. Git 协作流程

开始工作前：

```bash
cd /home/jetsonl7/summer-robotics-deploy
git status --short
git branch --show-current
git fetch origin
```

只有工作区干净且确定跟随主线时，才执行：

```bash
git pull --ff-only origin main
```

新功能使用独立分支：

```bash
git switch -c your-name/short-task-name
```

提交前：

```bash
git status --short
git diff --check
git diff
```

不要用 `git reset --hard`、`git clean -fd` 或强制推送处理看不懂的改动。数据、密钥、模型权重、机器标定和临时输出不进入 Git。

## 12. 常见问题

### `Robot hardware is already in use`

另一位队员或另一个终端正在持有硬件锁。先沟通并结束原实验，不要删除锁文件来抢占。

### 主机上没有 `/data`

正常。`/data` 是容器路径，主机上查看 `/home/jetsonl7/robot-data`。

### 主机上没有 `/workspace`

正常。`/workspace` 是容器路径，对应启动 `jetson_robot_exec.sh` 的那份仓库。

### `Permission denied`

先执行：

```bash
ls -ld PATH
ls -l PATH/TO/FILE
```

常见原因是把 `.py` 当可执行文件直接运行，或者容器生成了 root-owned 输出。不要直接放宽所有权限。

### `motor registers do not match ... calibration`

缓存标定与电机内部 homing offset 或限位不同。停止实验并核对具体差异；不要简单关闭校验或换一个名字相似的 JSON。

### 相机编号变化

不要写死 `/dev/video8` 等临时编号。通过 `--gemini`、`--wrist-a`、`--wrist-b` 使用启动脚本的稳定 USB 解析。

## 13. 一次标准实验的建议流程

```text
1. SSH 登录 Jetson
2. 确认现场人员、12V 断电能力和机械空间
3. 进入正式部署仓库
4. git status，确认正在运行哪份代码
5. 先运行无运动检查或 dry-run
6. 只映射所需设备
7. 通过统一入口启动实验
8. 保存输出到 /data 对应的 robot-data 目录
9. 停止并确认电机松扭矩、串口关闭
10. 记录结果；共享代码提交 Git，数据留在 robot-data
```

当命令来源不清楚时，开始前先回答三个问题：

1. 当前主机目录是哪一个？
2. 容器内 `/workspace` 实际映射哪份代码？
3. 输出写入容器临时目录，还是写入持久化的 `/data`？
