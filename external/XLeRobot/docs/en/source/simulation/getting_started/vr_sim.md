# XLeVR Tutorial

This guide explains how to use VR devices (currently Meta Quest3) for interactive control in XLeRobot simulation environments. It covers environment setup, dependencies, VR data flow, running demos, troubleshooting, and advanced usage.

---

## 1. Environment Setup

### 1.1 Dependencies

Ensure you have the following installed:

- Python 3.7+
- [ManiSkill](https://github.com/haosulab/ManiSkill)
- [XLeVR](../../../XLeVR/README.md) (included in this repo)

Example installation:

```bash
# Install ManiSkill and dependencies
pip install mani-skill
# Install XLeVR dependencies
cd XLeVR
pip install -r requirements.txt
```

---

## 2. VR Integration & Data Flow

### 2.1 VR Data Flow Overview

XLeVR uses a WebSocket server to stream real-time data from VR headsets and controllers, and provides a web UI via HTTPS for monitoring. The core data structure is `ControlGoal`, which includes position, orientation, button states, and more.

#### ControlGoal Main Fields

- `arm`: Device type ("left", "right", "headset")
- `target_position`: 3D coordinates (numpy array)
- `wrist_roll_deg`/`wrist_flex_deg`: Wrist roll/pitch angles
- `gripper_closed`: Whether the gripper is closed
- `metadata`: Extra info (trigger, thumbstick, etc)

### 2.2 Start the VR Monitor Service

From the `XLeVR` directory, run:

```bash
python vr_monitor.py
```

- The terminal will show an HTTPS address (e.g., `https://<your-ip>:8443`). Open this in your VR headset browser to see real-time control data.
- You can also copy `vr_monitor.py` to another project folder and edit the `XLEVR_PATH` variable at the top of the script.

---

## 3. Using VR Control in Simulation

### 3.1 Run the VR Control Demo

For ManiSkill environments, run:

```bash
python -m mani_skill.examples.demo_ctrl_action_ee_VR \
 -e "ReplicaCAD_SceneManipulation-v1" \
 --render-mode="human" \
 --shader="rt-fast" \
 -c "pd_joint_delta_pos_dual_arm" \
 -r "xlerobot"

```

- `-e` sets the environment (e.g., `ReplicaCAD_SceneManipulation-v1`, AI2THOR, Robocasa, etc.)
- `--render-mode` should be `human` for real-time visualization
- `-c` sets the control mode

### 3.2 Control Instructions

- **Move controllers**: Control the end-effector positions of both arms
- **Trigger**: Open/close the gripper
- **Thumbstick**: Move/rotate the robot base
- **Headset**: Used for viewpoint/pose data
- **Web UI**: Shows real-time device status and data

---


## 5. Troubleshooting

### 5.1 Startup Errors

- Check that `XLEVR_PATH` is set correctly
- If certificates (`cert.pem`/`key.pem`) are missing, generate them or disable HTTPS

### 5.2 No VR Data

- Make sure the VR headset is connected and accessing the correct HTTPS address
- Check firewall/port settings

### 5.3 Control Issues

- Check VR device drivers and firmware
- Ensure `vr_monitor.py` is running

---

## 6. Advanced Usage

### 6.1 Access VR Data in Code

You can access VR control goals directly in Python:

```python
from mani_skill.examples.vr_monitor import VRMonitor

monitor = VRMonitor()
monitor.initialize()
left_goal = monitor.get_left_goal_nowait()
right_goal = monitor.get_right_goal_nowait()
# left_goal/right_goal are ControlGoal objects
```

### 6.2 Data Structure Reference

See [XLeVR/README.md](../../../XLeVR/README.md) or the `vr_monitor.py` code for details.

---

## 7. References

- [ManiSkill Documentation](https://maniskill.readthedocs.io/en/latest/user_guide/datasets/scenes.html)
- [Oculus Reader Documentation](https://github.com/rail-berkeley/oculus_reader)
- [XLeVR/telegrip](https://github.com/DipFlip/telegrip)

---

For further questions, please open an issue or check the code comments.
