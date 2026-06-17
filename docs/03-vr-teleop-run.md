# 实验记录 03 · VR 遥操作真机跑通（整机双臂）

- **日期**：2026-06-17
- **状态**：✅ VR 遥操作跑通 —— 双手柄隔空控制双臂；待调参（灵敏度等）
- **平台**：Mac（Apple Silicon）+ XLeRobot + LeRobot 0.5.2 + Meta Quest 3S

> 软件 setup 细节见 [docs/02](02-vr-teleop-setup.md)；本篇是真机跑通 + 踩坑记录。

## 1. 成果

- **XLeRobot 文件整合完成**（`SO101Robot.py`→`lerobot/model/`，`robots/xlerobot`→`lerobot/robots/`）。
- **整机（双臂 + 底盘 + 头）连接 + 首次标定成功**，存 `~/.cache/huggingface/lerobot/calibration/robots/xlerobot/None.json`。
- **VR 遥操作跑通**：Quest 手柄 → WiFi → `vr_monitor` → 逆运动学 → 双臂跟随；扳机 = 夹爪。
- 修正了**左右手柄 ↔ 臂的反向**。

## 2. 新增/用到的工具

- [`tools/vr_teleop.py`](../tools/vr_teleop.py)：一键启动整机 VR 遥操作（设好 sys.path 后跑官方 `8_xlerobot_teleop_vr.py`）。
- [`tools/bus_monitor.py`](../tools/bus_monitor.py)：连续 ping 总线、实时报谁掉线，**定位松动接头**（今天靠它揪出白板断点）。已跨平台（用 `portutil`）。

## 3. 运行流程

```bash
conda activate lerobot
cd ~/Wichai/Hackathons/summer-robotics
python tools/vr_teleop.py
```
→ 整机连接（已标定则跳过标定）→ 打印 `https://<Mac-IP>:8443` → Quest 浏览器打开 → 接受自签证书 → **Start controller tracking** → 进 VR → 唤醒两个手柄 → 手臂跟随。

## 4. 今天最大的坑：电机控制板接触不良（反复发作）

- **症状**：scan 0 舵机 / `no status packet` / 移动臂时整条总线掉线 / **上扭矩瞬间掉线**。
- **诊断**：`bus_monitor.py` 连续监控 + 手拨各接头 → 定位白板断点在**右臂 1↔2 号之间** + **12V 桶头松**。
- **本质**：12V 在负载（上扭矩）下供不稳 + 舵机链/桶头接触电阻大 → brown-out。
- **解决**：12V 桶头插到底并固定、用 Anker **C2/C3（140W）** 大口、重插舵机链接头；两块板各跑 `bus_monitor` 确认"敲不掉"。
- **教训**：实体机器人接头要**插牢 + 固定 + 留线余量**；"端口在但 0 舵机" = **12V/总线问题，不是软件问题**。

## 5. 标定

- 整机标定与单臂是**两套**：整机用 `xlerobot/None.json`（电机名 `left_arm_*` / `right_arm_*` / `head_*` / `base_*`），和单臂的 `white_arm.json` / `black_arm.json`（so_follower）**不通用**。
- 整机标定已存 → 下次 `vr_teleop.py` 自动跳过标定（除非舵机偏移失配）。

## 6. 控制映射（`8_` 脚本）

| 你的动作 | 机器人 |
|---|---|
| 移动手柄（慢移） | 对应臂末端跟随（**delta 增量**控制）|
| 扣扳机 | 夹爪闭合 |
| 拨摇杆 | 头部 / 底盘 |

左手柄→左臂、右手柄→右臂（**已修正**：改 `8_` 脚本 518-519 行把两 goal 对调）。

## 7. 待办 / 待调

- **灵敏度太高** → 调 `8_` 脚本约 178-181 行的 `pos_scale` / `angle_scale` / `delta_limit`（调小）。
- 摇杆控制方式（绝对位置 vs 滑动增量）待理清。
- 接触可靠性：长期可能要更稳的供电/接线方案。
- **相机**：底盘 RGB + 头部 Orbbec 深度（深度相机未到）→ 之后接 `lerobot-record` 采数据。
- 路线下一步：相机出流 → 采数据 → V100 训 ACT → Jetson 部署。

## 8. ⚠️ 跨平台说明（重要）

VR 这套的**本机集成都在 `external/`（已 gitignore，不进仓库）**：XLeRobot 文件整合、`config_xlerobot` 端口、`XLEVR_PATH`、`8_` 脚本的左右对调。**这些是本机改动**，队友复现需各自重做（见 docs/02）。仓库里 `tools/*.py`（含 `vr_teleop` / `bus_monitor`）已跨平台。
