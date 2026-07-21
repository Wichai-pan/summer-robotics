# XLeVR教程

本指南说明如何使用VR设备(目前支持Meta Quest3)在XLeRobot仿真环境中进行交互式控制。涵盖环境设置、依赖项、VR数据流、运行演示、故障排除和高级用法。

---

## 1. 环境设置

### 1.1 依赖项

确保您已安装以下内容：

- Python 3.7+
- [ManiSkill](https://github.com/haosulab/ManiSkill)
- [XLeVR](../../../XLeVR/README.md) (包含在此仓库中)

安装示例：

```bash
# 安装ManiSkill和依赖项
pip install mani-skill
# 安装XLeVR依赖项
cd XLeVR
pip install -r requirements.txt
```

---

## 2. VR集成和数据流

### 2.1 VR数据流概述

XLeVR使用WebSocket服务器从VR头显和控制器流式传输实时数据，并通过HTTPS提供网页UI进行监控。核心数据结构是`ControlGoal`，包括位置、方向、按钮状态等信息。

#### ControlGoal主要字段

- `arm`: 设备类型 ("left", "right", "headset")
- `target_position`: 3D坐标 (numpy数组)
- `wrist_roll_deg`/`wrist_flex_deg`: 手腕翻滚/俯仰角度
- `gripper_closed`: 夹爪是否闭合
- `metadata`: 额外信息 (扳机、摇杆等)

### 2.2 启动VR监控服务

从`XLeVR`目录运行：

```bash
python vr_monitor.py
```

- 终端将显示一个HTTPS地址 (例如, `https://<your-ip>:8443`)。在您的VR头显浏览器中打开此地址以查看实时控制数据。
- 您也可以将`vr_monitor.py`复制到另一个项目文件夹，并编辑脚本顶部的`XLEVR_PATH`变量。

---

## 3. 在仿真中使用VR控制

### 3.1 运行VR控制演示

对于ManiSkill环境，运行：

```bash
python -m mani_skill.examples.demo_ctrl_action_ee_VR \
 -e "ReplicaCAD_SceneManipulation-v1" \
 --render-mode="human" \
 --shader="rt-fast" \
 -c "pd_joint_delta_pos_dual_arm" \
 -r "xlerobot" \

```

- `-e` 设置环境 (例如, `ReplicaCAD_SceneManipulation-v1`, AI2THOR, Robocasa等)
- `--render-mode` 应该设为 `human` 以进行实时可视化
- `-c` 设置控制模式

### 3.2 控制说明

- **移动控制器**: 控制双臂的末端执行器位置
- **扳机**: 打开/关闭夹爪
- **摇杆**: 移动/旋转机器人底座
- **头显**: 用于视点/姿态数据
- **网页UI**: 显示实时设备状态和数据

---

## 5. 故障排除

### 5.1 启动错误

- 检查`XLEVR_PATH`是否设置正确
- 如果证书(`cert.pem`/`key.pem`)缺失，生成它们或禁用HTTPS

### 5.2 无VR数据

- 确保VR头显已连接并访问正确的HTTPS地址
- 检查防火墙/端口设置

### 5.3 控制问题

- 检查VR设备驱动程序和固件
- 确保`vr_monitor.py`正在运行

---

## 6. 高级用法

### 6.1 在代码中访问VR数据

您可以在Python中直接访问VR控制目标：

```python
from mani_skill.examples.vr_monitor import VRMonitor

monitor = VRMonitor()
monitor.initialize()
left_goal = monitor.get_left_goal_nowait()
right_goal = monitor.get_right_goal_nowait()
# left_goal/right_goal是ControlGoal对象
```

### 6.2 数据结构参考

详情请参见[XLeVR/README.md](../../../XLeVR/README.md)或`vr_monitor.py`代码。

---

## 7. 参考资料

- [ManiSkill文档](https://maniskill.readthedocs.io/en/latest/user_guide/datasets/scenes.html)
- [Oculus Reader文档](https://github.com/rail-berkeley/oculus_reader)
- [XLeVR/telegrip](https://github.com/DipFlip/telegrip)

---

如有其他问题，请提交issue或查看代码注释。
