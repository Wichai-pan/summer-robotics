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

只读扫描（`external/scan_servos.py`）发现该板总线挂 **9 个 STS3215（model 777）**：

- **ID 1–6** = 这条臂的关节（shoulder_pan / shoulder_lift / elbow_flex / wrist_flex / wrist_roll / gripper）
- **ID 7–9** = 底盘 3 个全向轮

→ 即一块板挂「一条臂 + 部分底盘/辅助舵机」（LeKiwi 式），不是干净的"一臂一板"。脚本只驱动该臂的 ID 1–6。

### 机械臂身份对照（板序列号固定，端口名会变）

| 臂 | 颜色 | 板 USB 序列号 | 标定 id / 文件 | 实测舵机 |
|---|---|---|---|---|
| arm 1 | **白色** | `5B3D040988` | `white_arm` → `white_arm.json` | 9 个（臂 1-6 + 底盘轮 7-9） |
| arm 2 | **黑色** | `5B3D043224` | `black_arm` → `black_arm.json` | 8 个（臂 1-6 + 辅助 7-8） |

启动脚本 [`tools/arm_keyboard.py`](../tools/arm_keyboard.py) 按上面的序列号**自动找端口**，每条臂用**各自的标定文件**，互不覆盖。

## 5. 怎么找端口（端口名会变！）

板子 USB 芯片是 **WCH CH343**（Vendor `0x1a86`），**Mac 免装驱动**。

```bash
ls /dev/cu.usbmodem*          # Mac 上优先用 cu.，别用 tty.（tty 打开会等载波卡住）
```

- 本次端口：`/dev/cu.usbmodem5B3D0409881`（序列号 `5B3D040988` 在名字里，一般认得出这块板）。
- **换 USB 口名字可能变**，跑之前先 `ls` 确认一次。

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
