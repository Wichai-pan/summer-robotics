# 第一层：安全视觉 LLM 导航

这个目录是 XLeRobot 官方 **LLM Agent 控制** 教程的第一层落地：

`RGB 相机 → Gemini 视觉判断 → RoboCrew 工具调用 → 本地审计输出`

它的用途是验证完整的云端视觉 / 工具调用链路。当前所有工具都是 **DRY RUN**：它们只打印模型想执行的移动，不会打开机械臂或底盘串口，因此不会移动机器人。

## 已实现与尚未实现

| 内容 | 状态 |
| --- | --- |
| 实时 OpenCV 图像输入 | 已实现 |
| Gemini `gemini-3-flash-preview` 视觉推理与工具调用 | 已在头部 RGB 相机实测通过 |
| `按 W 前进 1 秒 / 前进距离 / 左转 / 右转 / 不动作` 的安全工具 | 已实现，全部为 dry run |
| 真实底盘运动 | 仅支持每次两次人工确认的 1 秒前进；默认不启用 |
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
`--supervised-forward`。它**只**支持 Gemini 请求的 `前进 1 秒`，而且每一步均有两次独立人工闸门：

1. Gemini 提议动作后，操作者重新检查路径并输入 `MOVE`；
2. 随后复用已验证的 `tools/base_forward_1s.py`，该脚本会再次要求输入 `MOVE`。

例如：

```bash
python agents/llm_navigation/agent.py --supervised-forward \
  --task "现场操作者确认正前方一秒路径清空；只选择一个安全动作。"
```

每次物理移动仅为一次键盘 `W` 映射的 1 秒前进，程序随后退出；要获取下一步，必须重新运行并重新确认。
任何 `NO ACTION`、转向、按距离前进或模型/相机错误都不会触发硬件动作。

## Jetson 的下一步（暂不执行）

把控制逻辑迁到 Jetson 后，先为相机与两块控制板建立 udev 固定名，并确认底盘三电机与急停流程。之后才会将本文件中的 dry-run 工具替换为 RoboCrew 官方的 `ServoControler` 和 `create_move_forward` / `create_turn_*` 工具。不能直接跳过这一步。

官方参照：XLeRobot 的 [LLM Agent 教程](../../external/XLeRobot/docs/zh/source/software/getting_started/LLM_agent.md)。
