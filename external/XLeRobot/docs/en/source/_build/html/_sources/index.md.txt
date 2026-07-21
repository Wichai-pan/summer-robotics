# XLeRobot 🤖

<img src="_static/XLeRobot.png" alt="Alt text" width="1200" />

[![GitHub](https://img.shields.io/badge/GitHub-XLeRobot-181717?logo=github&style=flat)](https://github.com/Vector-Wangel/XLeRobot) [![Stars](https://img.shields.io/github/stars/Vector-Wangel/XLeRobot?style=social)](https://github.com/Vector-Wangel/XLeRobot) [![Twitter/X](https://img.shields.io/twitter/follow/VectorWang?style=social)](https://twitter.com/VectorWang2) [![Apache License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) [![Discord](https://img.shields.io/badge/Discord-Join%20Chat-7289da.svg?logo=discord&logoColor=white)](https://discord.gg/s3KuuzsPFb)

<!-- [![en](https://img.shields.io/badge/lang-en-blue.svg)](..)
[![中文](https://img.shields.io/badge/lang-中文-brown.svg)](README_CN.md)

<div class="lang-switch">
  <a onclick="switchLang('en')" class="active">
    <img src="https://img.shields.io/badge/lang-en-blue.svg" alt="English" />
  </a>
  <a onclick="switchLang('zh')">
    <img src="https://img.shields.io/badge/lang-中文-brown.svg" alt="中文" />
  </a>
</div>

<div class="lang-en">
[English content...]
</div>

<div class="lang-zh">
[Chinese content...]
</div> -->



## Intro

**🚀 Bringing Embodied AI to Everyone - Cheaper Than an iPhone! 📱**

**💵 ~$660 cost and ⏰ <4hrs total assembly time!!**

*Built upon the giants: [LeRobot](https://github.com/huggingface/lerobot), [SO-100/SO-101](https://github.com/TheRobotStudio/SO-ARM100), [Lekiwi](https://github.com/SIGRobotics-UIUC/LeKiwi), [Bambot](https://github.com/timqian/bambot)*

---

## News

> Hardware: 
The hardware setup for XLeRobot 0.2.0 is officially out! This is the 1st official hardware version that is fully capable for autonomous household tasks, with <1000$ cost.
> 

> Simulation: 
XLeRobot 0.1.5 is officially out! The current version includes a short technical blog and a detailed Step-by-step Installation Instruction, along with all the urdf files, control scripts that can get you started in 10 min.
>

---

## 🌟 Why XLeRobot? 🌟

Let's break this down since **XLeRobot = XL + LeRobot**

### Why "LeRobot" Core?

- **Cheap Materials** 💴: 90% 3D printed components with affordable motors and electronics.
- **Easy Assembly** 🔨: 67 minutes to assemble 2 SO101 arms and configure motors.
- **Plug-&-Play** 🧩: Get robots running with simple pip install and a few lines of code.
- **Thriving LeRobot Community** 🌍:
World's largest low-cost robotics community featuring
    - Multiple [state-of-the-art pretrained AI models🧠](https://huggingface.co/lerobot), datasets📊, and tools🔨 ready for deployment.
    - 7000+ brilliant minds for brainstorming and discussions🧑‍🤝‍🧑.
    ![Description](https://github.com/user-attachments/assets/c685bf62-7c66-4382-a404-002142bb4690)

### Why "XL" Enhancement?

- 🏠 The field/market lacks affordable, stable, dual-arm home robots that match LeRobot's ease of assembly.
- 🖨️ Traditional 3D printed chassis suffer from limited durability, stability, and load capacity—making them impractical for daily use.
- ⚡ DIY mobile robots face power supply challenges, leading to complex wiring setups.
- 🤖 **XLeRobot** maintains compatibility with the LeRobot community's tabletop dual-arm SO-100/SO-101 configuration, enabling seamless code and policy transfer.

![Description](https://github.com/user-attachments/assets/38dfbefb-5d1d-41f5-ba3b-ccb5088ff6fc)

### Overall Advantages/Goals of XLeRobot

- **Cost-effective** 💴: Complete build costs \$660, or upgrade from existing SO100Arm and Lekiwi for \$250.
- **Easy upgrade** ⏫ (physical and electrical) for **Lekiwi** and **SO-100/SO-101**
    - Hardware: No motor ID changes or hardware modifications needed
    - Software: Identical tabletop single-arm/dual-arm setup—transfer your trained policies directly from SO-100/SO-101 arm
- **Practical and reliable** 💪: Performs many daily tasks comparable to $20,000 market alternatives.
    - More tasks demonstrated in the LeRobot hackathon in [Shenzhen](https://www.youtube.com/watch?v=_r9v04Rc3xA&ab_channel=SeeedStudio), [Shanghai](https://www.youtube.com/watch?v=1oXvINlYsls&ab_channel=SeeedStudio) and [San Jose](https://www.youtube.com/watch?v=QvzhsDliGII&ab_channel=SeeedStudio)([Winners](https://www.hackster.io/contests/embodiedAI#winners)), and the [first one](https://www.youtube.com/watch?v=i3D94400vq0&ab_channel=HuggingFace).
    - **Note**: Not currently designed for in-hand dexterity 🤹, heavy lifting (over 1kg per arm) 🏋️, or highly dynamic movements 🏃
- **Rich open-source resources** 📕
    - LeRobot's plug-and-play code🧩 and extensive AI model library🧠
    - Backed by an active, growing community of contributors🧑‍🤝‍🧑
- **⚠️Safety always matters⚠️**: XLeRobot has inherent physical hardware limitations (low-torque motors, short arm length, wheel-based) that make it physically almost incapable of harming humans, while still maintaining its ability to perform many household tasks.
    - **Low-torque motors**🦾: Even in the case of accidental contact, the robot is highly unlikely to cause injury. Additionally, its torque limitations prevent it from performing high-speed, dynamic movements.
    - **Short arm length**🦵: In the unlikely event that it's holding a sharp object, the robot can be quickly disabled by tipping over the IKEA cart.
    - **Wheel-based**🧑‍🦼‍➡️: It cannot climb over obstacles higher than 10cm, so you can easily restrict its movement using blocks or stairs in case of unauthorized access attempts.

These👆 are staged photos, but they demonstrate what the XLeRobot platform can achieve within its hardware limitations. (The scenes are a bit messy, but hey, that's life!)

---

## 🎯 Who is XLeRobot For?

- 🚀 **Startups & Labs**: Build prototypes faster with the world's cheapest modular platform
- 👩🔬 **Self Researchers**: Experiment with embodied AI without breaking the bank 💸
- 🎓 **Education Heroes**:
    - High School Teachers: Bring cutting-edge robotics to STEM classes 🧪
    - University Professors: Affordable platform for robotics/AI courses 📚
    - Students: From beginners to researchers 🎒→🎓
- 🤖 **DIY Enthusiasts**: Perfect for indoor projects - plant care, delivery bots, home automation 🌱📦

---

## Limitations

(Hey, for this price, what more could you ask for?)

- 🔒 Fixed height—adding a stable lifting platform would significantly increase costs and assembly difficulty
- 📏 Smaller workspace compared to Aloha—while we maximize the SO100 workspace, the arm has size limitations, though XLeRobot still handles most tasks effectively
- ⚖️ Limited payload capacity for a single arm—that's why we use the IKEA cart
- 🛒 Base movement precision may be affected by the IKEA cart wheels—this can be addressed through closed-loop feedback control

All things considered—cost, community support, ease of assembly, and practical utility—XLeRobot stands out as one of the most compelling low-cost robot for indoor application!

---

## Main Contributors

- [Me](https://vector-wangel.github.io/).
- Yuesong Wang: Mujoco simulation

This is just a small brick in the pyramid, made possible by [LeRobot](https://github.com/huggingface/lerobot), [SO-100](https://github.com/TheRobotStudio/SO-ARM100), [Lekiwi](https://github.com/SIGRobotics-UIUC/LeKiwi), and [Bambot](https://github.com/timqian/bambot). Thanks to all the talented contributors behind these detailed and professional projects.

Looking forward to collaborating with anyone interested in contributing to this project!

---

## Citation

If you want, you can cite this work with:

```
@misc{wang2025xlerobot,
    author = {Wang, Gaotian},
    title = {XLeRobot: A Practical Low-cost Household Dual-Arm Mobile Robot Design for General Manipulation},
    howpublished = "\\url{<https://github.com/Vector-Wangel/XLeRobot>}",
    year = {2025}
}

```

---

## 🪧 Disclaimer 🪧

> If you build, buy, or develop a XLeRobot based on this repo, you will be fully responsible for all the physical and mental damages it does to you or others.
>

---

```{toctree}
:maxdepth: 1
hardware/index
simulation/index
software/index
demos/index
relatedworks/index
```