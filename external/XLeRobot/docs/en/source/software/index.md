<!-- THIS IS ALL GENERATED DOCUMENTATION via generate_robot_docs.py. DO NOT MODIFY THIS FILE DIRECTLY. -->

# Software

Here we will show how to run XLeRobot under the lerobot framework.

### [Install LeRobot 🤗 and Move XLeRobot files](getting_started/install.md)

### Quick Guide

```{note}
If you haven't played with lerobot SO101 Arm before, it's recommended to test single arm setup teleop and play with it for a while first.
```

1. **Choose Control Method**: Joint control (example 0) for basic motor testing, end-effector control for teleop (example 1 & 6)
2. **Advanced Features**: Try dual-arm control (example 2) or vision-based control (example 3) for more complex tasks
3. **Full System**: Use keyboard (example 4), Xbox controller (example 5), or Switch Joycon (example 7) for complete XLeRobot teleop

All example scripts are located in the [`software/examples/`](https://github.com/Vector-Wangel/XLeRobot/tree/main/software/examples) directory and can be run directly after proper setup and calibration. Some examples needs additional calibration to ensure performance.

```{note}
For basic version of XLeRobot, you don't need a RaspberryPi. Just use your laptop and put it in the IKEA cart if you want to use the full system.
```

### [SO100/SO101 Arm Examples](getting_started/SO101.md)

### [XLeRobot Teleop](getting_started/XLeRobot_teleop.md)

### [Autonomous LLM Agent](getting_started/LLM_agent.md)

```{note}
The VLA tutorials below came from different teams in the community. Thanks a lot for their efforts!
```

### [VLA (1) ACT](getting_started/VLA_ACT.md)

### [VLA (2) SmolVLA and more](getting_started/VLA_smol.md)

### [VLA (3) pi0.5](getting_started/VLA_pi05.md)

### [Reinforcenment Learning (RL)](getting_started/RL.md)

### [Raspberri Pi Setup](getting_started/raspberry_pi_setup.md)


```{toctree}
getting_started/install
getting_started/SO101
getting_started/XLeRobot_teleop
getting_started/LLM_agent
getting_started/VLA_ACT
getting_started/VLA_smol
getting_started/VLA_pi05
getting_started/RL
getting_started/raspberry_pi_setup.md
```
