# 实验记录 05 · Jetson 接入与监督式视觉 LLM 导航

- **日期**：2026-07-23
- **平台**：Mac（Apple Silicon，开发/控制）+ XLeRobot + Jetson Orin Nano Super + Gemini 335 + 双臂/底盘
- **结论**：✅ Jetson 可经 SSH 无头访问；✅ 双臂、底盘与头部云台总线已定位；✅ Gemini 视觉 LLM 可在头部相机上安全决策；✅ 人工双确认下，底盘按键盘 W 映射前进 1 秒。❗连续无人移动、深度避障与目标人物跟随尚未启用。

## 1. Jetson 首次接入

通过 DP 显示器完成首次登录后，确认设备为 **NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super**，账户
`jetsonl7`，主机名 `jetsonl7-desktop`。系统信息：Ubuntu 22.04.5 LTS、Linux `5.15.148-tegra`、aarch64、Jetson Linux
R36.4.4（JetPack 6.2 系列）。系统从板载 microSD（约 113 GiB）启动；当时根分区约有 89 GiB 可用空间。

Mac 同一局域网可使用 mDNS 主机名连接：

```bash
ssh jetsonl7@jetsonl7-desktop.local
```

或在 `~/.ssh/config` 配置别名后使用 `ssh jetsonl7`。Wi-Fi IP 是 DHCP 分配的，会变化；优先使用上述 `.local` 名称。日后 Jetson 接通电源且自动连上相同 Wi-Fi 后，不需要显示器、鼠标或键盘即可 SSH。

常用只读检查：

```bash
hostnamectl
cat /etc/nv_tegra_release
df -h
ip -br addr
lsusb
tegrastats
```

**电源结论**：Jetson 应使用其额定圆口 DC 电源适配器供电；开发板 USB-C 不是可靠的整机供电输入。移动机器人时，需使用能提供对应 DC 电压/功率的电池逆变/供电方案，不能假设普通 USB-C 手机充电器能带动 Jetson。

## 2. 电机、端口与官方控制示例

控制板由 [`tools/portutil.py`](../tools/portutil.py) 按 USB 序列号识别，避免依赖会变化的 `/dev/cu.*`、`/dev/ttyACM*`：

| 控制板 | 序列号 | 已确认电机 |
| --- | --- | --- |
| 白臂板 | `5B3D040988` | 白臂 1–6；底盘三轮 7–9 |
| 黑臂板 | `5B3D043224` | 黑臂 1–6；头部 Gemini 云台 7、8；ID 9 目前无响应 |

今日已运行/验证：

- 官方单臂关节控制 `0_so100_keyboard_joint_control.py`；
- 官方单臂末端执行器控制 `1_so100_keyboard_ee_control.py`；
- 通过 [`tools/dual_arm_keyboard_ee.py`](../tools/dual_arm_keyboard_ee.py) 执行官方双臂 `2_` 示例（包装器只解决跨平台端口，逆运动学和键位保持官方逻辑）；
- 官方整机 `4_xlerobot_teleop_keyboard.py`：双臂、底盘可动；Rerun 弹窗为遥测可视化，非错误；
- [`tools/head_gimbal_test.py`](../tools/head_gimbal_test.py)：确认黑板 ID 7/8 都可读、可首次小幅响应，因此云台硬件/总线基本正常。多次连续原始位置写入没有稳定跟随，暂不用于任务控制，后续在 Jetson 上结合标定/位置范围排查；
- [`tools/base_forward_1s.py`](../tools/base_forward_1s.py)：复用已验证的 `base_keyboard.py` W 键运动学，白板三轮以 `0.12 m/s` 前进 1 秒，随后显式写零速度、松扭矩、关闭串口。已在地面实测方向正确且安全。

日常命令：

```bash
conda activate lerobot
python tools/portutil.py
python tools/arm_keyboard.py white        # 黑臂则为 black
python tools/dual_arm_keyboard_ee.py
python tools/head_gimbal_test.py
python tools/base_forward_1s.py
```

任何电机脚本只能有一个进程占用同一控制板；出现异响、方向异常或近碰撞时，立即断开 12V 电机供电。

## 3. 头部相机与底盘视觉

当前 Mac 在所有相机接入时的临时映射为：`0` 白臂手腕、`1` 黑臂手腕、`2` Gemini 335 头部 RGB。通过画面确认身份，不把编号当作永久配置：

```bash
python tools/preview_cameras.py 0 1 2 3 4
```

底盘低位摄像头尚未在本次 OpenCV 枚举中定位，因此当前导航只使用头部 Gemini RGB；Gemini 335 的深度数据尚未接入 LLM 安全门。手腕相机用于后续手部操作/VLA 数据，而非导航主视角。

## 4. 第一层 LLM Agent：已实测的安全闭环

安装 `robocrew==0.3.1` 后，`lerobot` 环境使用兼容的 0.5.0 包；`pip check` 通过。RoboCrew 0.3.1 导入时会在包目录创建记忆 SQLite，而 Conda 的 site-packages 不可写；项目的 [`agents/llm_navigation/agent.py`](../agents/llm_navigation/agent.py) 已将该本地数据库重定向到被 Git 忽略的 `agents/llm_navigation/runtime/`。

密钥只存放在被 Git 忽略的 `agents/llm_navigation/.env`：

```dotenv
GOOGLE_API_KEY=...
# 或 GEMINI_API_KEY=...
```

脚本支持两种模式：

1. **默认 dry run**：头部相机 `2` → Gemini `gemini-3-flash-preview` → RoboCrew 工具调用。模型可调用 `report_no_action`、转向、按距离前进或 `move_forward_one_second`，但只打印结果，不接触串口。
2. **单步监督执行**：加 `--supervised-forward` 后，只有模型选择 `move_forward_one_second` 才会继续；操作者必须两次输入 `MOVE`。第二次确认进入已独立验证的 `tools/base_forward_1s.py`，按 W 映射前进 1 秒并退出。

实测结果：

- 在人、桌椅、床等遮挡的画面中，模型正确调用 `report_no_action`；
- 在操作者明确确认“一秒路径清空、人物不在该路径中”的条件下，模型调用 `move_forward_one_second`；
- 两次 `MOVE` 后底盘成功前进 1 秒、停止并松扭矩。

运行命令：

```bash
# 仅视觉决策（绝不移动）
python agents/llm_navigation/agent.py \
  --task "描述前方画面；若不确定或有障碍物，不要移动。"

# 已完成底盘前进验证后才可使用；每次仅执行一小步且需两次确认
python agents/llm_navigation/agent.py --supervised-forward \
  --task "现场操作者确认机器人正前方按键盘 W 的一秒行程内地面清空；只选择一个最安全动作。"
```

## 5. 明日续做

1. 保持 `MOVE` 双重人工确认，不开启连续无人移动；连续移动前必须接入深度距离、超时停机和可用急停。
2. 在 Jetson 为 Gemini、两只手腕相机和两块控制板建立 udev 固定名，消除 `/dev/video*` / `/dev/ttyACM*` 拔插漂移。
3. 在 Jetson 安装/验证 Orbbec SDK、RoboCrew 与相机流；先复现头部 RGB dry run，再迁移单步监督执行。
4. 排查云台 ID 7/8 的连续位置控制（标定、限位、键盘映射），保留 ID 9 无响应为待查硬件项。
5. 定位底盘低位摄像头；将 Gemini 深度纳入最小人/障碍距离安全门后，再讨论放宽人工确认。
