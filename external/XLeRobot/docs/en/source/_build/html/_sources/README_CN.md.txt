# XLeRobot 🤖

<img src="_static/XLeRobot.png" alt="Alt text" width="1200" />

[![en](https://img.shields.io/badge/lang-en-blue.svg)](index.md)
[![中文](https://img.shields.io/badge/lang-中文-brown.svg)](..)
<!-- [![es](https://img.shields.io/badge/lang-es-green.svg)](README_ES.md)
[![de](https://img.shields.io/badge/lang-de-orange.svg)](README_DE.md)
[![fr](https://img.shields.io/badge/lang-fr-white.svg)](README_FR.md)
[![日本語](https://img.shields.io/badge/lang-日本語-yellow.svg)](README_JP.md) -->

> [!NOTE] 
> 硬件：[XLeRobot 0.2.0的硬件配置](https://github.com/Vector-Wangel/XLeRobot/blob/main/XLeRobot_0_2_0_hardware/README.md)正式发布！这是第一个官方硬件版本，完全能够执行自主家务任务，成本低于1000美元。

> [!NOTE] 
> 仿真：**XLeRobot 0.1.5** 正式发布！当前版本包含 [一篇简短的技术博客](simulation/sim_CN.md) and 和详细的 [**分步安装指南**](simulation/sim_guide_CN.md), 并附带所有urdf文件和控制脚本，让您可以在10分钟内开始使用复现demo。 

> [!NOTE] 
> 实机：**XLeRobot 0.1.0** 正式发布！当前版本包括详细的**材料清单**、**3D打印模型和说明**，以及**逐步组装指南**。可用Lekiwi代码库在单臂版本上**运行遥操作测试**（由另一个跟随臂控制）。不到4000元，不到4小时即可复现demo。

# XLeRobot 🤖

[![Apache License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) [![Twitter/X](https://img.shields.io/twitter/follow/VectorWang?style=social)](https://twitter.com/VectorWang2) [![Discord](https://img.shields.io/badge/Discord-Join%20Chat-7289da.svg?logo=discord&logoColor=white)](https://discord.gg/s3KuuzsPFb)
---

**🚀 让具身AI走向每个人 - 比小米手机还便宜！ 📱**  
**💵 <4000￥ 和 ⏰ <4小时总组装时间!!**

*站在巨人的肩膀上: [LeRobot](https://github.com/huggingface/lerobot), [SO-100](https://github.com/TheRobotStudio/SO-ARM100), [Lekiwi](https://github.com/SIGRobotics-UIUC/LeKiwi), [Bambot](https://github.com/timqian/bambot)*

---
## ⚽ XLeRobot Playground （0.1.5）

**XLeRobot 0.1.5** 正式发布！当前版本包含 [一篇简短的技术博客](simulation/sim_CN.md) and 和详细的 [**分步安装指南**](simulation/sim_guide_CN.md), 并附带所有urdf文件和控制代码，让您可以在10分钟内开始使用并复现下面展示的demo。 

<video width="100%" controls>
  <source src="https://github.com/user-attachments/assets/e66d8cb5-7a02-4445-b6d9-793057996f87" type="video/mp4">
  Your browser does not support the video tag.
</video>


---



## 🌟 为什么选择XLeRobot？ 🌟
让我们来分解一下，因为**XLeRobot = XL + LeRobot**

<table>
  <tr>
    <td>
      
### 为什么选择"LeRobot"核心？
- **廉价材料** 💴: 90%的3D打印组件，配合经济实惠的电机和电子元件。
- **简易组装** 🔨: 仅需2小时的组装时间。
- **即插即用** 🧩: 通过简单的pip安装和几行代码让机器人运行起来。
- **蓬勃发展的LeRobot社区** 🌍:
  世界上最大的低成本机器人社区，特色包括
  - 多个[最先进的预训练AI模型🧠](https://huggingface.co/lerobot)、数据集📊和工具🔨，随时可以部署。
  - ![image](https://github.com/user-attachments/assets/c685bf62-7c66-4382-a404-002142bb4690)

  - 6,000+聪明才智的头脑进行头脑风暴和讨论🧑‍🤝‍🧑。
    
    </td>
    </tr>
    <tr>
    <td>
 
### 为什么需要"XL"增强？ 
- 🏠 该领域/市场缺乏价格合理、稳定的双臂家用机器人，能够与LeRobot的简易组装相匹配。
- 🖨️ 传统3D打印底盘耐久性、稳定性和负载能力有限——使其不适合日常使用。
- ⚡ DIY移动机器人面临电源供应挑战，导致复杂的接线设置。
- 🤖 **XLeRobot**保持与LeRobot社区的桌面双臂SO100配置的兼容性，实现代码和策略的无缝转移。
  
    </td>
  </tr>
 </table>       

![image](https://github.com/user-attachments/assets/38dfbefb-5d1d-41f5-ba3b-ccb5088ff6fc)


### XLeRobot的整体优势/目标

- **经济实惠** 💴: 完整构建成本为$660，或者从现有SO100Arm和Lekiwi升级仅需$250。
- **轻松升级** ⏫ (物理和电气)对于**Lekiwi**和**SO100**
    - 硬件：无需更改电机ID或硬件修改
    - 软件：与桌面单臂/双臂设置相同——直接从SO100臂转移您训练好的策略
- **实用可靠** 💪: 执行许多日常任务，可与市场上$20,000的替代品相媲美。
 
    - 更多任务在LeRobot黑客马拉松中展示，包括[深圳](https://www.youtube.com/watch?v=_r9v04Rc3xA&ab_channel=SeeedStudio)、[上海](https://www.youtube.com/watch?v=1oXvINlYsls&ab_channel=SeeedStudio)和[圣何塞](https://www.youtube.com/watch?v=QvzhsDliGII&ab_channel=SeeedStudio)([获奖者](https://www.hackster.io/contests/embodiedAI#winners))，以及[第一个](https://www.youtube.com/watch?v=i3D94400vq0&ab_channel=HuggingFace)。
    - **注意**：目前不适用于手内灵巧操作🤹、重物提升(每臂超过1kg)🏋️或高度动态运动🏃
- **丰富的开源资源** 📕
    - LeRobot的即插即用代码🧩和广泛的AI模型库🧠
    - 由活跃、不断增长的贡献者社区支持🧑‍🤝‍🧑
- **⚠️安全始终重要⚠️**: XLeRobot具有固有的物理硬件限制(低扭矩电机、短臂长、轮式基础)，使其几乎不可能伤害人类，同时仍然保持执行许多家庭任务的能力。
  - **低扭矩电机**🦾: 即使在意外接触的情况下，机器人也极不可能造成伤害。此外，其扭矩限制防止其执行高速、动态运动。
  - **短臂长**🦵: 在不太可能的情况下，如果它持有尖锐物体，可以通过翻倒IKEA推车快速禁用机器人。
  - **轮式基础**🧑‍🦼‍➡️: 它无法爬过高于10cm的障碍物，所以在未授权访问尝试的情况下，您可以使用障碍物或楼梯轻松限制其移动。

<img width="598" alt="Examples" src="https://github.com/user-attachments/assets/ca418604-13fc-43bf-811a-6036a4455a69" />

这些👆是摆拍照片，但它们展示了XLeRobot平台在其硬件限制内可以实现的功能。(场景有点凌乱，但嘿，这就是生活！)




---
## 🎯 演示 0.1.0 🎯
> [!NOTE]
> 目前是**单臂版本**实现Lekiwi，由另一个跟随臂以**3倍速度**远程操作。

https://github.com/user-attachments/assets/2e9eb3c9-af16-4af2-8748-8f936278c8eb

---

## 💵 总成本 💵

> [!NOTE] 
> 成本不包括3D打印、工具、运输和税费。

| 价格| 美国  | 欧盟  | 中国 |
|---------|----:|----:|----:|
| **从零开始构建** |  **~$660**  |  **~€650**  |  **~¥3900**  |
| **从2个SO100臂升级**  |  **~$400**  |  **~€440**  |  **~¥2400**  |
| **从1个Lekiwi(底座+臂)升级** |  **~$370**  |  **~€350**  |  **~¥1900**  |
| **从1个Lekiwi和1个SO100臂升级** |  **~$250**  |  **~€240**  |  **~¥1200**  |

详情请参见[材料清单](BOM.md)。

---
---
## 🚀 开始使用 🚀
> [!NOTE] 
> 我自己也是硬件新手，所以我想让这个教程对所有同为初学者的朋友友好。

> [!NOTE] 
> 如果你完全不懂编程，请至少花一天时间熟悉基本的Python、Ubuntu和Github(借助B站和AI的帮助)。至少你应该知道如何设置ubuntu系统、git克隆、pip安装、使用解释器(VS Code、Cursor、Pycharm等)，Conda环境，以及直接在终端中运行命令。

1. 💵 **购买零件**: [材料清单](BOM.md)
2. 🖨️ **打印你的部件**: [3D打印](3Dprint.md)
3. 🔨 ~~复仇者~~: [**集结**!](Assembly.md)
4. 💻 **软件**: [让你的机器人动起来!](Software.md)
---
---
> [!NOTE] 
> 上面的内容提供了构建**XLeRobot**的高效指导。下面的内容更详细地解释了项目的目的和愿景。

## 🛠️ 硬件介绍 🛠️

**XLeRobot** = Lekiwi + 1x SO100臂 + **宜家RÅSKOG推车** + **Anker电池**

= 2x SO100臂 + 3x全向轮 + 树莓派 + **宜家RÅSKOG推车** + **Anker电池**

### 📜基本规格

- **重量**📏: ~12kg。成人可轻松抬起。
- **工作空间**🦾:
  - 高度范围: 距地面~0.5m-1.25m
  - 宽度范围: 距推车边缘~0.36m。
  - 能够完成许多家庭任务。
- **电池**🔋:
  - 300W最大输出: 足以为12V版本双臂 + lekiwi底座 + 树莓派(~180W最大)供电
  - 288Wh容量: 通常可运行10小时以上
  - 280W最大输入: 1小时即可充满
  - 可选太阳能板☀: 用于无限充电

> [!NOTE]
> *所有计算都由你的PC处理——树莓派仅通过WiFi管理数据通信 📶*

<table>
  <tr>
    <td>
      
### 为什么选择宜家RÅSKOG推车？
- 🌎 全球可用，设计标准化
- 💰 经济实惠
- 🏗️ 结构简单但坚固
- 🔧 金属网格底部便于组件安装
- 📦 完美适合存储和运输
- 📏 理想高度适合常见家庭表面——从炉灶到咖啡桌
- 📏 紧凑的占地面积几乎适合任何房间(感谢宜家的周到设计)


    </td>
    </tr>
    <tr>
    <td>
    
### 为什么选择Anker SOLIX C300电源站？ 
- 🌍 全球可用
- ⚡ 288Wh容量，300W最大输出功率，280W最大充电功率
- 🔌 通过三条USB-C充电线为12V双臂、底座和树莓派提供全容量电力——消除复杂接线
- 🔋 卓越的电池寿命: 正常使用12+小时，密集操作8小时，1小时完全充电
- 💡 集成照明用于夜间操作
- ☀️ 可选太阳能板安装，提供持续电力
- 🎒 多功能且可拆卸——可兼作紧急备用电源或露营电源

    </td>
  </tr>
</table>
<img width="843" alt="1745819677076" src="https://github.com/user-attachments/assets/ad081621-1e69-4bc6-a50f-d89cf92f35c3" />

即使你不积极使用机器人，这两种产品在日常使用中仍然很有价值。

---

## 💻 软件介绍 💻
以下是如何控制机器人并使其智能化：

### 🕹️ 基本控制

- **关节**(电机角度)控制 → 主从臂控制

- **末端执行器姿态**控制 → VR远程控制
  
> [!NOTE]
> 对于第一个版本，我们主要关注硬件。LeRobot代码保持不变。你可以通过将一个臂连接到树莓派，另一个连接到桌面进行远程控制来重现Demo 0.1.0。**XLeRobot的LeRobot代码**将很快作为我们的首要任务进行更新。


### 🧠 通向通用具身机器智能的路径(待办)






### 🔈广告:
- **我们的实验室**: [Rice RobotPI Lab](https://robotpilab.github.io/)
    - 我们的愿景包括使用[**时间中的笼罩**](https://robotpilab.github.io/publication/caging/)和**漏斗式操作**方法，在不完美的现实世界条件下实现稳健的物体操作——包括感知噪声、网络延迟和[接触丰富](https://robotpilab.github.io/publication/collision-inclusive-manipulation/)环境。
- **模拟平台**(我个人偏好): [Maniskill](https://www.maniskill.ai/)
    - 🚀快速GPU加速用于并行模拟
    - 🎨通过光线追踪实现美丽的逼真视觉效果
    - 🪶轻量级、一致且用户友好(相比Isaac Lab，我个人观点)
    - 🤖支持[多种机器人](https://maniskill.readthedocs.io/en/latest/software/index.html)(包括[SO100臂](https://x.com/Stone_Tao/status/1910101218241978537))
    - 我自己玩出来的一个截屏：
    - ![6dc9d8459f6809dc04d178e68e63c6a](https://github.com/user-attachments/assets/ce45f108-7551-43dd-8317-0dead3e2f406)



---
## 未来计划

### 硬件
<table>
  <tr>
    <td>
      
**紧急**

- 🔧 添加两种臂底座选项：夹持式(当前)或螺钉安装式
- 🛠️ 添加与宜家推车金属网格完全兼容的连接板
    </td>
    </tr>
    <tr>
    <td>
    
**近期**

- 📸 在头部添加RealSense深度相机，补充手部RGB相机，实现精确环境感知
- 🔦 添加激光雷达和SLAM功能，实现类似Roomba的家庭导航
- 👆 基本触觉感应
    </td>
  </tr>
</table>


> [!NOTE]
> 虽然更高级的升级完全可能(如切换到Jetson处理器、升级底盘或使用更好的电机)，但这些会与本项目的核心使命相矛盾：**创建世界上最经济实惠、易于安装、即插即用的通用机器人开源平台**。但这些升级可以在未来作为可选附加组件列出，而不是主要方向。

### 软件

(软件更新也将取决于LeRobot社区的发展)
<table>
  <tr>
    <td>
      
**紧急**

- ⚙️ 基本控制算法
- 🎮 优化的末端执行器控制
- 🎲 Maniskill模拟环境
- 🕶️ Quest3 VR控制和远程操作
- 🤖 使用Lerobot代码库中现有VLA模型的简单任务
    </td>
    </tr>
    <tr>
    <td>
    
**近期**

- 🎯 基于AprilTag的精确校准
- 🗺️ 自主导航
- 🌐 数字孪生对齐，用于sim2real应用
- 🧠 世界模型和基于物理的稳健操作
- 💬 与MCP连接，直接利用LLMs
    </td>
  </tr>
</table>

---

## 🎯 XLeRobot适合谁？

- 🚀 **初创公司和实验室**: 使用世界上最便宜的模块化平台更快地构建原型
- 👩🔬 **自研人员**: 在不破产的情况下实验具身AI 💸
- 🎓 **教育英雄**:
  - 高中教师: 将前沿机器人技术带入STEM课堂 🧪
  - 大学教授: 机器人/AI课程的经济实惠平台 📚
  - 学生: 从初学者到研究人员 🎒→🎓
- 🤖 **DIY爱好者**: 完美适合室内项目 - 植物护理、递送机器人、家庭自动化 🌱📦
---

## 局限性

(要啥自行车？)

- 🔒 固定高度——添加稳定的升降平台将显著增加成本和组装难度
- 📏 与Aloha相比工作空间较小——虽然我们最大化了SO100的工作空间，但手臂有尺寸限制，不过XLeRobot仍能有效处理大多数任务
- ⚖️ 单臂负载能力有限——这就是为什么我们使用宜家推车
- 🛒 底座移动精度可能受到宜家推车轮子的影响——这可以通过闭环反馈控制解决
  
综合考虑——成本、社区支持、组装便捷性和实用性——XLeRobot脱颖而出，成为室内应用最具吸引力的低成本机器人之一！




---

## 主要贡献者

目前只有[我](https://vector-wangel.github.io/)。将来当更多人加入这个开源项目时，一定会更新这个列表。他们也将被添加到引用列表中作为作者之一。

这只是金字塔中的一小块砖，由[LeRobot](https://github.com/huggingface/lerobot)、[SO-100](https://github.com/TheRobotStudio/SO-ARM100)、[Lekiwi](https://github.com/SIGRobotics-UIUC/LeKiwi)和[Bambot](https://github.com/timqian/bambot)共同实现。感谢这些详细且专业项目背后所有才华横溢的贡献者。

期待与任何有兴趣为该项目做出贡献的人合作！

> [!NOTE]
> 目前忙于论文截稿日期，将从2025年7月开始公开寻求合作和投资。

与Anker或宜家没有关联(但我们喜欢瑞典肉丸！🍝)

---

## 引用

如果您愿意，可以使用以下方式引用本工作：

```bibtex
@misc{wang2025xlerobot,
    author = {Wang, Gaotian},
    title = {XLeRobot: A Practical Low-cost Household Dual-Arm Mobile Robot Design for General Manipulation},
    howpublished = "\url{https://github.com/Vector-Wangel/XLeRobot}",
    year = {2025}
}
```
未来一定会添加更多作者(如LeRobot和Lekiwi的开发者，在我亲自与他们确认后)。

---

## 🪧 免责声明 🪧
尽管我个人认为XLeRobot应该是目前物理意义上的安全系数最高的机器人之一了，但是：
> [!NOTE]
> 如果您基于此仓库构建XLeRobot，您将对其对您或他人造成的所有财产，身体和精神损害负全部责任。