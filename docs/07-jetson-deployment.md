# Jetson 机载部署

本页记录 ForestBridge 将机器人 USB、控制与推理统一迁移到 Jetson Orin Nano Super 的可重复流程。所有电脑只通过 SSH 访问 Jetson；同一时刻只能有一个进程拥有电机硬件。

## 1. 已确认的硬件映射

| 设备 | Jetson 当前节点 | 稳定身份 |
|---|---|---|
| Gemini 335 | `/dev/video0`–`/dev/video7` | USB `2bc5:0800`，SN `CP0F463000WA`，USB 3 / 5 Gbps |
| 手腕相机 A | `/dev/video8`、`/dev/video9` | USB physical path `1-2.4.1`，应使用 `index0` |
| 手腕相机 B | `/dev/video10`、`/dev/video11` | USB physical path `1-2.4.3`，应使用 `index0` |
| 白板/底盘侧 | `/dev/ttyACM0` | USB serial `5B3D040988` |
| 黑板/黑臂侧 | `/dev/ttyACM1` | USB serial `5B3D043224` |

`/dev/videoN` 和 `/dev/ttyACMN` 只是本次启动的编号。控制板应按 serial / `by-id` 识别；两只手腕相机具有重复的厂商序列号，必须按 physical path / 自定义 udev 别名识别。

## 2. 一次性主机权限

先在 Jetson 本机终端或 SSH 中执行：

```bash
sudo usermod -aG dialout,docker jetsonl7
```

随后退出所有 `jetsonl7` 会话并重新登录（重启也可以），确认：

```bash
id
```

输出必须同时包含 `dialout` 和 `docker`。不要长期使用 `chmod 666 /dev/ttyACM*`，也不要把密码写进脚本。

## 3. 拉取部署代码

```bash
ssh jetsonl7
cd /home/jetsonl7/summer-robotics-deploy
git status --short
git pull --ff-only origin main
```

如果 `git status --short` 有输出，先停止，不要 reset、clean 或覆盖队友的改动。

## 4. 为什么使用容器

当前源码中的 LeRobot 0.5.2 要求 Python 3.12 和 Torch 2.7 以上；Jetson 主机只有 Python 3.10。部署基线是 NVIDIA 的 Jetson iGPU 镜像：

```text
nvcr.io/nvidia/pytorch:25.06-py3-igpu
```

它提供适用于 Jetson 的 Python 3.12 与 GPU Torch。不要在主机或镜像中执行通用的 `pip install torch`，也不要使用仓库的巨型 `requirements-ubuntu.txt` 覆盖 NVIDIA Torch。

NVIDIA 25.06 iGPU Torch 使用 NumPy 1.x ABI；项目镜像因此固定 NumPy 1.26.4 和 OpenCV 4.11。虽然这比 LeRobot 通用依赖中声明的 NumPy 2.x 更旧，但它是保证 `torch.from_numpy` 在本机可用的 Jetson 专用兼容覆盖。

Orbbec 官方 `pyorbbecsdk2 2.1.1` 提供 Python 3.12 / Linux ARM64 wheel，但其通用依赖会升级 NumPy 和 OpenCV。镜像只安装固定版本的 vendor wheel（`--no-deps`）；已验证其 `pyorbbecsdk` 模块可与上述 Jetson ABI 组合导入。

## 5. 构建与无硬件自检

基础镜像较大，首次下载需要稳定网络和足够时间：

```bash
cd /home/jetsonl7/summer-robotics-deploy
./scripts/jetson_build_image.sh
./scripts/jetson_container_smoke.sh
```

自检脚本不会映射 USB、相机、串口、密钥或标定文件，因此不能让机器人运动。成功标准：

- 架构为 `aarch64`；
- Python 为 3.12；
- 能导入 LeRobot 0.5.2；
- NumPy、OpenCV 和 `torch.from_numpy(...).cuda()` 可用；
- `pyorbbecsdk` 可导入；
- `cuda True`；
- GPU 名称可见。

## 6. 私有机器状态

这些文件不进入 Git，已单独复制到 Jetson：

- `~/.cache/huggingface/lerobot/calibration/robots/so_follower/black_arm.json`
- `~/.cache/huggingface/lerobot/calibration/robots/so_follower/white_arm.json`
- `~/.cache/huggingface/lerobot/calibration/robots/xlerobot/None.json`
- `/home/jetsonl7/summer-robotics-deploy/agents/llm_navigation/.env`
- `/home/jetsonl7/summer-robotics-deploy/yolo11n.pt`

容器运行脚本后续只映射所需的只读标定目录、项目目录和明确的设备节点；不会默认使用 `--privileged`。

## 7. 后续安全顺序

1. 无 USB 的 GPU / LeRobot 自检；
2. 安装并验证 Linux aarch64 Orbbec SDK；
3. 只读识别两个控制板和电机 ID；
4. Gemini 单帧 RGB-D；
5. 两只手腕相机逐个 MJPEG 出流，再测试双路；
6. 加跨用户硬件锁；
7. 现场操作者清空范围后，才进行单关节小动作和底盘短动作。

在第 6 步完成前，团队成员可以共同查看代码和感知输出，但不能同时启动任何两个电机控制进程。

## 8. 统一硬件容器入口

所有会访问机器人 USB 的命令都应通过：

```bash
./scripts/jetson_robot_exec.sh [设备参数] -- COMMAND [ARG...]
```

设备参数包括 `--gemini`、`--white`、`--black`、`--ports-readonly`、`--wrist-a` 和 `--wrist-b`。入口只映射明确申请的设备，不使用 `--privileged`，并通过 `/tmp/forestbridge-xlerobot.lock` 阻止两个团队成员同时启动硬件容器。

常用无运动检查：

```bash
# 控制板身份；设备节点以只读权限映射，脚本不会打开串口
./scripts/jetson_ports_smoke.sh

# Gemini RGB-D 5 帧快照；不会映射电机串口
./scripts/jetson_orbbec_smoke.sh 5
```

RGB-D 结果按 UTC 时间戳写入 `/home/jetsonl7/robot-data/tmp/jetson-gemini-smoke-*.{jpg,json}`，宿主用户拥有这些文件。
