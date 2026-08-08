# 第一层：安全视觉 LLM 导航

这个目录是 XLeRobot 官方 **LLM Agent 控制** 教程的第一层落地：

`RGB 相机 → Gemini 视觉判断 → RoboCrew 工具调用 → 本地审计输出`

它的用途是验证完整的云端视觉 / 工具调用链路。当前所有工具都是 **DRY RUN**：它们只打印模型想执行的移动，不会打开机械臂或底盘串口，因此不会移动机器人。

## 已实现与尚未实现

| 内容 | 状态 |
| --- | --- |
| 头部 RGB 输入 | 已实现：OpenCV（手腕相机/普通 UVC）或 Orbbec SDK 同帧 RGB-D（Gemini 335） |
| Gemini `gemini-3-flash-preview` 视觉推理与工具调用 | 已在头部 RGB 相机实测通过 |
| `按 W 前进 1 秒 / 前进距离 / 左转 / 右转 / 不动作` 的安全工具 | 已实现，全部为 dry run |
| 真实底盘运动 | 支持固定前进/小转向，每次均须两次人工确认；可选 Gemini 335 深度安全门 |
| 语音输入、云台扫描、VLA 抓取 | 下一层，不在本测试中 |

## 一次性准备

在仓库根目录、已激活 `lerobot` 环境时执行：

```bash
cp agents/llm_navigation/.env.example agents/llm_navigation/.env
```

然后只编辑 `agents/llm_navigation/.env`：

```dotenv
GOOGLE_API_KEY=粘贴你的_Gemini_API_key
```

也兼容 `GEMINI_API_KEY=...`，但程序会在运行时将其映射给 RoboCrew 所需的 `GOOGLE_API_KEY`。
`.env` 已被根目录 `.gitignore` 忽略；不要把 key 粘到 Python 文件、文档、终端截图或 Git 提交中。

## 运行（Mac 上先验证）

先接好已经验证可出图的头部相机。当前这台 Mac 的映射是：`0` 白臂手腕、`1` 黑臂手腕、`2` 头部
Gemini 的 RGB；启动前仍建议确认：

```bash
conda activate lerobot
python tools/preview_cameras.py 0 1 2
```

确认后运行一次视觉判断：

```bash
python agents/llm_navigation/agent.py --camera 2 \
  --task "描述画面。如果正前方没有人、障碍物或台阶，只选择一个最安全的动作；否则不要移动。"
```

终端出现 `DRY RUN` 或 `NO ACTION` 即表示 Gemini 成功调用了受限工具；无论结果是什么，本阶段均没有硬件运动。

## 单步监督执行（仅在已验证底盘 W 映射后）

确认 `python tools/base_forward_1s.py` 在地面上的方向、安全性均与键盘 `W` 一致后，才可附加
`--supervised-forward`。它支持 Gemini 请求的 `前进 1 秒`或约 16° 小转向，而且每一步均有两次独立人工闸门：

1. Gemini 提议动作后，操作者重新检查路径并输入 `MOVE`；
2. 随后复用已验证的 `tools/base_forward_1s.py`，该脚本会再次要求输入 `MOVE`。

例如：

```bash
python agents/llm_navigation/agent.py --supervised-forward \
  --task "现场操作者确认正前方一秒路径清空；只选择一个安全动作。"
```

每次物理移动均为一个固定离散动作，程序随后退出；要获取下一步，必须重新运行并重新确认。
任何 `NO ACTION`、按距离前进或模型/相机错误都不会触发硬件动作。

## Gemini 335 深度安全门（Mac 实测）

Gemini 的 Python SDK 独立安装在 `orbbec-depth` Conda 环境，不能装入 `lerobot` 环境（两者对
`av` 的版本要求冲突）。主程序通过子进程调用只读的 [深度探针](../../tools/orbbec_depth_probe.py)，
因此深度检查不会打开电机串口。

在 Mac 上，Orbbec 采集通常需要管理员权限。`--camera-backend orbbec` 让官方 SDK 同时拥有 Gemini
335 的 RGB 与 Depth；它会在**每一个决策步骤开始前**采集 15 帧同帧 RGB-D，
并将中心 ROI 的 P10/中位数作为上下文交给 Gemini，避免把画面远处的人误判为紧贴底盘的障碍物。若 Gemini
随后提出前进，程序会在显示第一次 `MOVE` 提示前**再采集一次**；近端 P10 小于 `0.20 m`、没有有效帧或
采集失败时，程序会拒绝该次前进。小转向不依赖这项深度读数，但仍需要两次人工确认。

先在同一个终端执行一次 `sudo -v`。这会显示密码提示并建立短时 sudo 凭据；程序内部会使用无交互
`sudo -n`，因此凭据过期时会立即拒绝前进，而不会在后台等待密码。读取深度时程序会暂时关闭头部 RGB
流、读完立刻重开，避免 Gemini 335 的 RGB 与 Depth 流在 macOS 上争用设备。对于 Gemini 335，优先使用
下面的 `--camera-backend orbbec`；它不打开 OpenCV 的头部 UVC 流，因此不会发生这种争用。

```bash
sudo -v

python agents/llm_navigation/agent.py --camera 2 \
  --camera-backend orbbec \
  --supervised-steps --max-steps 2 \
  --depth-gate --depth-sudo --depth-min-m 0.20 \
  --task "现场操作者会在每一步前重新检查短路径安全；只选择一个最安全的小动作。"
```

`0.20 m` 是**硬性不动作距离**，不是“在距离障碍物 20 cm 处仍可完整前进 1 秒”的许可。由于一次 W
动作约 12 cm，接近工作台时仍应由操作者在 `MOVE` 提示处判断余量；下一阶段再增加 5 cm 的慢速靠近动作。
可单独验证深度而不控制电机：

```bash
sudo -E /Users/huataipan/miniconda3/envs/orbbec-depth/bin/python \
  tools/orbbec_depth_probe.py --json --samples 15
```

## 第二层：实时深度闭环接近检查点

固定的 1 秒前进不能精确停在工作距离。`tools/orbbec_depth_stream.py` 会用一个常驻 Orbbec SDK
pipeline 发布中心 ROI 的深度 P10；`tools/base_approach_to_distance.py` 在本地读取这个流，以低速
`0.04 m/s` 前进，并在 P10 小于等于 `0.50 m`、深度流超过 `0.75 s` 未更新、达到超时上限、或收到
`Ctrl-C` 时写零轮速并松扭矩。LLM 不参与这项刹车判断。

先做无电机验证（机器人静止时它会在超时后停止）：

```bash
sudo -v

conda activate lerobot
python tools/base_approach_to_distance.py \
  --stop-m 0.50 --speed-mps 0.04 --max-duration-s 5 \
  --depth-sudo --dry-run
```

只有确认深度读数稳定、底盘前方和双臂周围清空、且能立即断开 12 V 之后，才可移除 `--dry-run`。程序会
要求输入 `APPROACH` 一次；这授权的是“低速接近到 0.50 m 检查点”，不是之后的机械臂或更近距离操作。

```bash
sudo -v

python tools/base_approach_to_distance.py \
  --stop-m 0.50 --speed-mps 0.04 --max-duration-s 30 \
  --depth-sudo
```

## 第三层第 1 步：YOLO 目标框深度（只检测）

`tools/orbbec_rgbd_aligned_stream.py` 在 `orbbec-depth` 环境常驻运行官方 SDK，并对 Depth 做软件
对齐到 Color；`tools/yolo_orbbec_depth_detect.py` 在 `lerobot` 环境运行 YOLO。两者通过本地运行时文件
传递**同一帧序列**的 RGB JPEG、对齐深度数组与元数据，不共享 OpenCV/SDK 设备句柄。

检测器的主距离 `center` 是检测框几何中心附近小块的有效深度中位数，优先代表目标中心；`near` 是框中央 50%
深度的 P10，仅作为“该框内可能有更近部分”的保守提示。这样比整个框的中位数更少受背景、框边缘和深度洞影响。
该阶段只显示窗口，绝不打开任何电机串口。

```bash
sudo -v

conda activate lerobot
python tools/yolo_orbbec_depth_detect.py \
  --depth-sudo --classes bottle person
```

按 `Q` 或 `Esc` 关闭。第一次运行若没有本地 `yolo11n.pt` 权重，Ultralytics 会提示下载；下载完成后再启动
检测。先用瓶子分别在约 1.0 m、0.7 m、0.5 m 处检查框内距离是否稳定，才继续做“不运动的目标接近决策”。

## 第三层第 2 步：目标接近决策（dry run）

在检测窗口中附加 `--target` 与 `--dry-run-approach` 后，本地规则只根据指定目标的框中心深度与水平偏角，
叠加显示 `TURN_LEFT`、`TURN_RIGHT`、`FORWARD`、`ARRIVED`、`TOO_CLOSE_STOP` 或 `TARGET_LOST -> STOP`。
它不会导入串口包，也不会控制电机；这是验证目标居中、距离和阈值逻辑的一步。目标锁会先获取一个指定类别的
框，之后只接受相邻帧位置连续的候选框；短暂漏检显示 `HOLDING`，连续 8 帧找不到才显示 `TARGET_LOST`，并对
目标中心距离作轻微 EMA 平滑，避免在相似物体之间来回切换。

```bash
python tools/yolo_orbbec_depth_detect.py \
  --depth-sudo --target cup --dry-run-approach \
  --standoff-m 0.50
```

例如当前画面中 `cup` 位于约 0.63 m、且接近画面中心时，预期显示 `FORWARD`；将它放至约 0.50 m 会显示
`ARRIVED`。人、宠物或不确定类别绝不作为接近目标；它们将在之后的实际运动阶段成为额外停止条件。

## 第三层第 3 步：LLM 受限任务分发（仍不运动）

现在可以让 Gemini 只作高层语义选择，例如“接近画面中央的杯子，并在约 0.50 m 处停下”。它**不能直接调用**
电机、速度、持续时间或底盘串口；可调用的 `request_target_approach` 仅接受当前 YOLO 可识别的非生命物体：
`bottle`、`book`、`cell phone`、`cup`、`keyboard`、`remote`，以及 0.20–1.00 m 的停靠距离。程序收到这个请求后
只打印一条交给上一节本地 YOLO RGB-D 跟踪器的 dry-run 命令。

```bash
conda activate lerobot
python agents/llm_navigation/agent.py \
  --camera-backend orbbec \
  --depth-sudo \
  --target-approach-dry-run \
  --task "找到画面中清楚可见的杯子；如果确定是杯子，请请求在 0.50 米处停靠的目标接近 dry-run。不要请求任何底盘移动。"
```

预期输出是类似 `target=cup, requested standoff=0.50 m` 的结构化交接，以及可复制的
`tools/yolo_orbbec_depth_detect.py --target cup --dry-run-approach ...` 命令。若看不到目标或类别不在白名单，
模型应调用 `report_no_action`。这正是职责边界：LLM 选目标/意图；本地模块负责目标锁、对齐深度、转向/停止规则；
物理运动仍需另行建立并验证，不会由此开关启用。

## 第三层第 4 步：受监督的目标接近循环

`tools/target_approach_supervised.py` 是 LLM 高层交接之后的本地执行器。输入是固定的 `--target` 和停靠距离；
它以对齐 RGB-D + YOLO 为每步选择 `turn_left_small`、`turn_right_small`、`forward_1s`、靠近停靠距离时的
`forward_small`（约 3.6 cm），或 `STOP`。它不接受自由速度或持续时间。默认 **DRY RUN**，没有串口依赖。

先把杯子单独放好、让人离开头部相机视野，再跑不运动的验证：

```bash
conda activate lerobot
python tools/target_approach_supervised.py \
  --depth-sudo --target cup --standoff-m 0.50 --max-actions 3
```

预期会输出每步的锁定状态、杯子中心距离、水平偏角、前方中心 P10，以及将要选择的动作。画面中可以有远处的操作者；
这不会自动停止，但每一步仍由操作者的两次 `MOVE` 确认实际短路径清空。目标丢失、深度无效或前方 P10 ≤ 0.20 m
会输出 `STOP`；`person` 本身仍不能作为接近目标。检测器显示 `HOLDING` 时只是视觉预览可暂时保留旧框，
但本脚本不会用旧框继续物理移动：它会先等待最多 4 秒让目标恢复为 `TRACKING`，仍不能恢复才 `STOP`。

只有 dry-run 中的判断稳定，且路径和双臂都已清空时，才可加 `--execute`。一次运行默认最多 3 步，必要时可显式设为
最多 8 步；每一个固定动作都需要：

1. 本脚本输入一次 `MOVE`；
2. 已验证的 `base_motion_step.py` 再输入一次 `MOVE`。

任何一次不输入 `MOVE`、目标丢失或底盘通信出错，都会停止且不继续下一步。该脚本只允许固定小步；它不是
“无监督跟随人/物体”的实现。

## Jetson 的下一步（暂不执行）

把控制逻辑迁到 Jetson 后，先为相机与两块控制板建立 udev 固定名，并确认底盘三电机与急停流程。之后才会将本文件中的 dry-run 工具替换为 RoboCrew 官方的 `ServoControler` 和 `create_move_forward` / `create_turn_*` 工具。不能直接跳过这一步。

官方参照：XLeRobot 的 [LLM Agent 教程](https://github.com/Vector-Wangel/XLeRobot/blob/main/docs/zh/source/software/getting_started/LLM_agent.md)。
