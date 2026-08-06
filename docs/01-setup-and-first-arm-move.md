# 实验记录 01 · 环境搭建 & 首次让机械臂动起来（Step 0）

- **日期**：2026-06-16
- **状态**：✅ 完成 —— 单臂键盘控制跑通，标定已保存
- **平台**：Mac（Apple Silicon, macOS 15.7）+ XLeRobot + LeRobot 0.5.2

> 本步目标不是做产品，而是把「平台从开箱到能控制」跑通。链路打通后，后续采数据/训练/部署都是"换数据"。

---

## 1. 成果

- conda 环境 `lerobot` 装好（Python 3.12）。
- 一条机械臂：**端口识别 → 舵机通信 → 标定 → 键盘控制关节**，全部跑通。

## 2. 硬件连线（每条臂一套）

电机控制板 = **Waveshare Bus Servo Adapter (A) V1.1**。

| 接口 | 接什么 | 备注 |
|---|---|---|
| A/B 跳线 | **B（USB ~ SERVO）** | 必须在 B，USB 才能控制舵机 |
| DC 桶口（9~12.6V） | **PD→DC 12V 线** → Anker 的 **C1/C2/C3**（100/140W）口 | 给舵机供电 |
| USB-C（标 USB） | 普通 USB-C 数据线 → Mac | 只是数据 |
| 两个白色 JST 口 | 舵机总线（已接好，别动） | |

⚠️ **USB-C 只供数据，舵机的劲来自 12V**。两条线都要接，缺一不动。
⚠️ Anker 别用 A1/A2（USB-A 12W）、C4（15W 太小）、CAR SOCKET、SOLAR IN。

## 3. 软件环境（一次性，队友各自在自己电脑做）

源码放在 `external/`（已 gitignore，不进仓库）。

```bash
# 1) conda 环境（注意：lerobot 0.5.2 要求 Python ≥ 3.12，3.10 装不上）
conda create -y -n lerobot python=3.12
conda activate lerobot

# 2) 装 LeRobot（SO-101 用 Feetech 舵机）
mkdir -p external && cd external
git clone --depth 1 https://github.com/huggingface/lerobot.git
cd lerobot && pip install -e ".[feetech]"
pip install "pynput>=1.7.8,<1.9.0"     # 键盘遥操作后端

# 3) 拿 XLeRobot（示例脚本在 software/examples/）
cd .. && git clone --depth 1 https://github.com/Vector-Wangel/XLeRobot.git
```

- 验证：`python -c "import lerobot, torch; print(lerobot.__version__, torch.__version__)"`
- 单臂脚本 `0_` 用 lerobot 自带的 `so_follower` + `keyboard`，**不用搬文件**。
- 整机/EE/VR 脚本（`1_`,`2_`,`4_`,`8_`）才需把 `XLeRobot/software/src/{model,robots,teleporators}` 叠加进 `lerobot/src/lerobot/` 对应目录（以后再做）。

## 4. 硬件拓扑（重要）

只读扫描（`external/scan_servos.py`）确认白臂板总线挂 **9 个 STS3215（model 777）**；黑臂板当前有 8 个响应：

- **ID 1–6** = 这条臂的关节（shoulder_pan / shoulder_lift / elbow_flex / wrist_flex / wrist_roll / gripper）
- **ID 7–9** = 底盘 3 个全向轮

→ 即一块板挂「一条臂 + 部分底盘/辅助舵机」（LeKiwi 式），不是干净的"一臂一板"。脚本只驱动该臂的 ID 1–6。

### 机械臂身份对照（板序列号固定，端口名会变）

| 臂 | 颜色 | 板 USB 序列号 | 标定 id / 文件 | 实测舵机 |
|---|---|---|---|---|
| arm 1 | **白色** | `5B3D040988` | `white_arm` → `white_arm.json` | 9 个（臂 1-6 + 底盘轮 7-9） |
| arm 2 | **黑色** | `5B3D043224` | `black_arm` → `black_arm.json` | 8 个（臂 1-6 + 深度相机云台两个轴 7、8；ID 9 当前未响应） |

启动脚本 [`tools/arm_keyboard.py`](../tools/arm_keyboard.py) 按上面的序列号**自动找端口**，每条臂用**各自的标定文件**，互不覆盖。

固定抓取轨迹采集时，可在每个关键姿态轻按 `P`；终端会输出两行：`SAVED_TARGET_JSON=...` 是本脚本 P 控制器实际追踪的目标，`MEASURED_ENCODER_JSON=...` 是 LeRobot 读回的编码器坐标。由于此遗留脚本有额外的手写标定，两者数值**不会相同**；低速回放只使用前者。按顺序保存 `预抓取 → 下探 → 合爪 → 抬起`，`P` 本身不发送任何运动命令。

## 5. 怎么找端口（端口名会变！）

板子 USB 芯片是 **WCH CH343**（Vendor `0x1a86`），**Mac 免装驱动**。

```bash
ls /dev/cu.usbmodem*          # Mac 上优先用 cu.，别用 tty.（tty 打开会等载波卡住）
```

- 本次端口：`/dev/cu.usbmodem5B3D0409881`（序列号 `5B3D040988` 在名字里，一般认得出这块板）。
- **换 USB 口名字可能变**，跑之前先 `ls` 确认一次。

> **其实不用手动找了**：所有脚本通过 [`tools/portutil.py`](../tools/portutil.py) 按板序列号在 **Mac / Windows / Linux** 上自动解析端口，端口名变了也不用管。想看本机当前串口： `python tools/portutil.py`。Windows 用法见下面 §10。

### 手腕摄像头预览

两只手腕 UVC 相机接好后，先用 LeRobot 查索引并保存静态图确认物理位置：

```bash
lerobot-find-cameras opencv --record-time-s 2
```

再同时预览两路（当前 Mac 上常为 `0 1`；**拔插后索引会变，以实际检测结果为准**）：

```bash
python tools/preview_cameras.py 0 1
# 可请求 720p/30fps：python tools/preview_cameras.py 0 1 --width 1280 --height 720 --fps 30
```

按 `q` 或 `Esc` 退出。画面上标有实际索引和分辨率；遮住一只镜头即可确认哪路是左手/右手。macOS 首次运行需在「隐私与安全性 → 相机」允许终端 App。

## 6. 怎么跑（让臂动）

**在自己的终端里跑**（键盘控制要抓本机键盘）。

**跑前准备：**
- macOS：`系统设置 › 隐私与安全性 › 输入监控`（和`辅助功能`）勾上你的终端 App，授权后重启终端。
- 安全：清空这条臂周围，一手扶臂，另一只手能随时断电（拔 C1 的 PD 线 / 关 Anker）。

```bash
conda activate lerobot
cd ~/Wichai/Hackathons/summer-robotics
python tools/arm_keyboard.py white      # 白臂；黑臂用 black
# 自动按板序列号找端口、用各自标定文件；端口名变了也不用管
```

> 也可直接跑原始示例 `external/XLeRobot/software/examples/0_so100_keyboard_joint_control.py`，但它要手输端口、且两臂共用一个标定文件（会互相覆盖）。**优先用上面的 `tools/arm_keyboard.py`。**

**交互提示：**
1. 端口**自动解析**（按板序列号），不用手输。
2. `recalibrate? (y/n)`：**首次选 y 标定；以后选 n 复用**。
3. 标定两步（仅首次）：
   - ① `Move to the middle ... ENTER`：把臂摆成各关节大致居中的姿势 → 回车。
   - ② `Move all joints ... Recording ... ENTER`：臂此时是软的，**用手把每个关节慢慢掰到两端极限**，看屏幕 MIN/MAX 拉开后再回车。（`wrist_roll` 连续旋转，程序自动跳过。）
4. 之后 3 秒缓慢归零（**扶住臂**）→ 进入键盘控制。

**按键：**
```
Q/A 肩转   W/S 肩抬   E/D 肘   R/F 腕屈   T/G 腕转   Y/H 夹爪   X 退出
```

### 双臂末端执行器控制（官方 `2_` 示例，Mac 入口）

官方双臂脚本将 Linux 端口 `/dev/ttyACM0`、`/dev/ttyACM1` 写死。运行项目入口
[`tools/dual_arm_keyboard_ee.py`](../tools/dual_arm_keyboard_ee.py) 会按白、黑板序列号自动解析端口，
仅在内存中替换端口后执行**官方原有**双臂逆运动学、键位和 P 控制逻辑，不改动 vendor 源码。

```bash
python tools/dual_arm_keyboard_ee.py
```

启动前两条臂都必须固定、接好 12V，且运动范围清空。脚本会询问两条臂是否重新标定；已有正确的
`white_arm.json` / `black_arm.json` 时选 `n`，随后会让两臂同时归零约 3 秒。

```text
白臂：7/y 底座，8/u X，9/i Y，=/[ 腕俯仰，0/o 腕转，-/p 夹爪
黑臂：h/b 底座，j/n X，k/m Y，,/. 腕俯仰，;/l 腕转，'/ 夹爪
X：退出（先返回启动姿态）
```

### 深度相机云台独立测试（黑板 ID 7、8）

黑板的 ID 7、8 分别是深度相机云台两个轴。若整机遥操作中云台无反应，先退出整机
脚本以释放串口，再运行下面的独立测试。它不连接或命令手臂/底盘，每次输入仅让一个
云台轴相对当前位置移动约 5°，用来区分键盘映射问题和电机/总线问题：

```bash
python tools/head_gimbal_test.py
```

确认云台周围清空后输入 `yes`，再用 `a/d` 测 ID 7、`j/l` 测 ID 8；每个输入需要按
Enter，`q` 退出。退出时脚本会松开两个云台电机扭矩。

### 底盘地面直行 1 秒（复用键盘 W 映射）

在确认三轮的 ID 与方向后，运行下面的独立测试会复用已验证的 `base_keyboard.py` 中 **W 键**
运动学和默认速度（0.12 m/s）直行 **1 秒**，再自动发停止指令并松开底盘扭矩。它只会操作白板
ID 7/8/9，不会控制白臂或调用 Gemini：

```bash
python tools/base_forward_1s.py
```

运行前将双臂收好，清空机器人正前方至少 2 米，并确保旁边有人可立即断开 12V 电源。脚本会先
检查三轮响应，并要求逐字输入 `MOVE` 才会运动；输入任何其它内容都会取消。

## 7. 标定会不会重做

不会。每条臂存各自的文件：

```
~/.cache/huggingface/lerobot/calibration/robots/so_follower/white_arm.json   # 白臂
~/.cache/huggingface/lerobot/calibration/robots/so_follower/black_arm.json   # 黑臂
```

且 homing offset 写进舵机 EEPROM（断电不丢）。**下次 `recalibrate?` 选 `n` 即复用**，两臂互不覆盖。这份标定是后续采数据/训练/部署的地基，不是一次性的。

> 旧的 `None.json`（早期共用脚本留下的）已作废，可删可不删：`rm ~/.cache/huggingface/lerobot/calibration/robots/so_follower/None.json`

## 8. 常见坑

| 现象 | 原因 / 解决 |
|---|---|
| 标定报 `same min and max` | 第②步没真把关节掰到两端 → 重做，慢慢掰满 |
| 按键没反应 | 输入监控权限没生效 → 授权后重启终端 |
| 端口打不开/占用 | 用 `cu.` 不用 `tty.`；确认没别的程序占串口 |
| 舵机超时/无响应 | 检查 12V：PD 线在 C1、桶头插紧、Anker 开机 |
| 任何异响/猛动 | 立刻拔 C1 的 PD 线断电，拍照排查 |

## 9. 下一步

- 接第二条臂 + 底盘（同样套路，板子各自 12V + USB）。
- 遥操作采数据（脚本 `4_`/`8_`）→ V100 训练 ACT → Jetson 部署。

## 10. Windows / 跨平台（与 Mac 共用同一套脚本）

脚本已跨平台：`tools/*.py` 通过 [`tools/portutil.py`](../tools/portutil.py) 按**板子 USB 序列号**自动找端口，Mac / Windows / Linux 通用，端口名变了也不用管。**Mac 上行为和以前完全一样**（仍走 `/dev/cu.usbmodem...`）。

**Windows 与 Mac 的差异（就这几点）：**

| 事项 | Mac | Windows |
|---|---|---|
| 串口名 | `/dev/cu.usbmodem...` | `COMx`（如 `COM7`）|
| WCH 驱动 | 免装 | **要装** CH343SER（[wch-ic.com](https://www.wch-ic.com/downloads/CH343SER_EXE.html)），否则设备管理器里根本没有 COM 口 |
| 键盘权限 | 要在 隐私与安全性 › 输入监控 给终端授权 | **不用**，pynput 直接能用（普通终端即可，不必管理员）|
| conda / pip 安装 | 同 §3 | **完全一样**（`conda create -n lerobot python=3.12` …）|

**Windows 跑法（PowerShell）：**

```powershell
conda activate lerobot
cd <仓库路径>\summer-robotics
python tools\portutil.py            # 先看本机串口 + 能不能认出白/黑板
python tools\arm_keyboard.py white  # 同 Mac，自动找 COM 口
python tools\base_test.py           # 底盘逐轮测试（务必先垫高离地！）
python tools\base_keyboard.py       # 底盘键盘遥控
```

**认不出端口 / 想手动指定**（任一脚本都能跳过自动解析）：
- 命令行直接给端口：`python tools/arm_keyboard.py white COM7`、`python tools/base_keyboard.py COM7`、`python tools/base_test.py COM7`
- 或环境变量：PowerShell `$env:XLEROBOT_PORT="COM7"`；bash `export XLEROBOT_PORT=COM7`

怎么知道是哪个 COM？跑 `python tools/portutil.py`，或拔插板子看 设备管理器 › 端口(COM 和 LPT) 里哪个 CH343 出现/消失。

> CH343 + 1,000,000 波特率 + SO-101/STS3215 在 Windows 上都受支持：`scservo_sdk` 和 `lerobot` 底层都是 pyserial，直接吃 `COMx`，无需改动代码。`COM9` 及以上 pyserial 会自动加 `\\.\` 前缀，不用自己处理。
