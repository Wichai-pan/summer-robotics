# 实验记录 08 · Eye-to-hand 诊断与 Jetson 整机迁移

- **日期**：2026-08-07
- **平台**：Mac（开发端）+ Jetson Orin Nano Super 8GB（机器人主机）+ XLeRobot + Gemini 335 + 两只手腕相机
- **目标**：结束 Mac 直连全部 USB 的工作方式，把代码、GPU 推理、相机和控制板统一迁移到 Jetson，并保留可重复、安全、适合团队 SSH 协作的执行入口。
- **结果**：✅ Jetson GPU 容器与全部相机/控制板已验收；✅ 全局硬件锁已验证；✅ 原黑臂键盘控制器完成 SSH 输入适配；❌ 本轮面霜标记 eye-to-hand 拟合未通过，不授权自动 IK；⏳ Jetson 上原黑臂控制器的真实全范围复测留到下次现场实验。

## 1. 当日实验起点：九点 eye-to-hand 拟合

前一阶段已采集 9 组黑臂编码器姿态与 Gemini 中浅蓝面霜标记的三维坐标。本日完成离线 URDF 约束拟合及独立留出检查：

| 指标 | 结果 |
|---|---:|
| 训练点 RMSE | 10.64 mm |
| 留出第 9 组误差 | 93.41 mm |
| 判定 | **FAIL / motion locked** |

失败原因不是“IK 完全不可用”，而是面霜表面颜色质心并非刚性固定特征：遮挡、观察方向和重新夹持会改变检测区域。第 8、9 组检测框分别约 `20×12 / 110 px` 与 `137×202 / 8211 px`，不能视作同一个稳定物理点。因此：

- 保留拟合器、9 组样本和失败产物作为诊断证据；
- 不把拟合变换写入真实运动配置；
- 下一轮改用刚性固定的 ArUco/AprilTag 或明确点标记，并在不断电、不松夹的一次会话中重采。

## 2. Jetson 系统盘点

通过 SSH 对 Jetson 进行只读审计，确认：

| 项目 | 实测状态 |
|---|---|
| 主机 | `jetsonl7-desktop`，用户 `jetsonl7` |
| 系统 | Ubuntu 22.04.5，L4T R36.4.4，aarch64 |
| 硬件 | Jetson Orin Nano Engineering Reference Developer Kit Super |
| CPU / RAM | 6× Cortex-A78AE；约 7.4 GiB RAM |
| 存储 | 113 GiB 根分区，约 89 GiB 可用 |
| GPU 软件 | CUDA toolkit 12.6，TensorRT 10.3 |
| 功耗模式 | `25W` |
| 网络 | Wi-Fi；本地 SSH 别名 `jetsonl7` 可用 |
| 用户组 | `dialout`、`video`、`render`、`docker` 均已生效 |

主机 Python 是 3.10，而仓库内 LeRobot 0.5.2 要求 Python 3.12 和 Torch 2.7 以上，因此没有在主机上强装通用 PyPI Torch。

## 3. 可重复 GPU 容器

新增 Jetson 专用容器定义与脚本，以 NVIDIA `nvcr.io/nvidia/pytorch:25.06-py3-igpu` 为基础：

- Python 3.12；
- NVIDIA Torch 2.8.0a0，`torch.cuda.is_available() == True`；
- 仓库内 vendored LeRobot 0.5.2；
- NumPy 1.26.4 + OpenCV 4.11，避免 NVIDIA Torch 的 NumPy 2 ABI 冲突；
- `pyorbbecsdk2 2.1.1` Linux ARM64 wheel，以 `--no-deps` 保留上述 ABI 组合。

关键文件：

```text
deploy/jetson/Dockerfile
deploy/jetson/requirements-control.txt
scripts/jetson_build_image.sh
scripts/jetson_container_smoke.sh
```

无硬件 smoke test 已验证 Python、LeRobot、NumPy→Torch→CUDA、OpenCV 和 Orbbec Python 模块。

## 4. USB 与相机验收

全部 USB 已从 Mac 改接到 Jetson。稳定身份如下：

| 设备 | 当日节点 | 稳定识别方式 | 结果 |
|---|---|---|---|
| Gemini 335 | `/dev/video0`–`7` | `2bc5:0800`，SN `CP0F463000WA` | USB 3 / 5 Gbps，RGB-D 3/3、5/5 有效 |
| 手腕相机 A | `/dev/video8/9` | physical path `2.4.1`，index0 | 1280×720 MJPEG 正常；边缘有旧黑斑 |
| 手腕相机 B | `/dev/video10/11` | physical path `2.4.3`，index0 | 1280×720 MJPEG 正常 |
| 白板/底盘侧 | `/dev/ttyACM0` | serial `5B3D040988` | 解析为 white |
| 黑板/黑臂侧 | `/dev/ttyACM1` | serial `5B3D043224` | 解析为 black |

两只手腕相机最初黑屏的原因是镜头盖未取下；取下后画面正常。两者 USB 产品/序列字符串重复，因此不能依赖 `/dev/videoN` 或 `by-id`，后续必须按物理 USB path 建稳定别名。

## 5. 私有机器状态迁移

GitHub 只保存可共享源码。以下机器状态已单独复制到 Jetson，不进入 Git：

```text
~/.cache/huggingface/lerobot/calibration/robots/so_follower/black_arm.json
~/.cache/huggingface/lerobot/calibration/robots/so_follower/white_arm.json
~/.cache/huggingface/lerobot/calibration/robots/xlerobot/None.json
agents/llm_navigation/.env
yolo11n.pt
```

已再次确认 `black_arm.json` 包含六个关节标定项。容器将标定目录只读挂载；API key 和模型权重不会被提交。

## 6. 统一硬件入口与并发保护

新增统一入口：

```bash
./scripts/jetson_robot_exec.sh [设备参数] -- COMMAND [ARG...]
```

它只映射命令明确请求的 Gemini、手腕相机或控制板，不使用 `--privileged`。所有硬件容器共享 `/tmp/forestbridge-xlerobot.lock`；实测第一个容器运行时，第二个容器立即以状态码 3 拒绝启动。该锁解决多名队友同时 SSH 时的端口抢占，但直接 `docker run` 会绕过锁，因此团队操作中禁止使用。

## 7. 黑臂 SSH 键盘控制迁移

先实现的 `tools/arm_terminal.py` 是保守诊断器，默认只允许启动姿态附近的小范围移动。现场反馈确认它不等同于迁移前已成功使用的控制器，不能替代正式键盘操作。

随后直接修改原 `tools/arm_keyboard.py`：

- 保留原 Q/A、W/S、E/D、R/F、T/G、Y/H 映射；
- 保留原 P 控制、完整活动范围、`P` 姿态输出和退出回位；
- 保留 `black_arm.json` 标定及“是否重标定”询问；
- 仅新增 `--terminal`，用 POSIX TTY 逐键读取代替 SSH 环境中不可用的 `pynput`；
- `Esc` 映射为原来的 `X` 退出行为；
- 增加异常退出时的终端恢复、松扭矩和串口关闭。

Jetson 命令：

```bash
ssh -t jetsonl7
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_robot_exec.sh --interactive --black -- \
  python3 tools/arm_keyboard.py black --terminal
```

输入 `n` 复用已有标定。该脚本与 Mac 原版一样会先移动到零位，因此真实复测必须清空完整运动范围。今日已完成 CLI、容器导入和伪终端后端测试，但未把“Jetson 上完整黑臂运动成功”写成已验证结论。

## 8. 团队远程访问讨论

同一局域网内已可通过 `ssh jetsonl7` 管理 Jetson。针对国内队友，讨论了以下方案：

1. 首选 Tailscale：各自账户，只分享 Jetson 单机，不共享账户或 `jetsonl7` 密码；
2. 若中国—芬兰链路不稳定，再考虑香港/日本或合规大陆 VPS + frp；
3. 队友应使用独立 Ubuntu 用户和 SSH 公钥；不默认授予 `docker`、`dialout`、`sudo`；
4. 跨国真实运动前必须增加断线 watchdog、现场使能和现场断电人员。

Tailscale/frp 今日仅完成方案选择讨论，尚未在 Jetson 安装。

## 9. 当日结论与下一步

### 已完成

- Jetson 从“能登录的裸系统”变为可复现的机器人 GPU/控制主机；
- Gemini、两只手腕相机和两块控制板全部在线；
- GitHub 成为代码源，Jetson 部署 clone 可快进更新；
- 私有标定、密钥和权重与 Git 分离；
- 硬件最小映射和全局锁生效；
- 迁移前成功的黑臂脚本获得 SSH 键盘后端。

### 未完成或失败

- 面霜颜色质心 eye-to-hand 拟合失败，不允许驱动真实 IK；
- 手腕相机 A/B 尚未最终贴上白臂/黑臂物理标签；
- SSH 下相机连续可视化仍需 headless/web 输出；
- 原黑臂脚本的 Jetson 真实运动复测尚未完成；
- 公网/跨国接入与断线安全尚未部署。

### 下次实验顺序

1. 现场运行原 `arm_keyboard.py black --terminal`，验证归零、六关节、夹爪、`P` 保存和退出回位；
2. 给两只手腕相机确认物理归属并建立稳定别名；
3. 增加 headless 相机快照/视频查看方式；
4. 安装并实测 Tailscale，只开放代码、日志和感知访问；
5. 使用刚性标记重新采集 eye-to-hand 数据，留出验证通过后再恢复自动 IK。
