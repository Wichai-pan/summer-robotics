# VLA (2) SmolVLA, ACT

本文档解释了如何使用**XLeRobot**进行：
1. 使用**双臂SO-101**设置和**三摄像头数据收集**训练和运行**SmolVLA**
2. 训练和运行**ACT (Action Chunking with Transformers)**策略
3. 使用**VR控制**XLeRobot
<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/demoshow.gif?raw=true" width="80%" alt="VR Demo GIF"/>
<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/demoshow2.gif?raw=true" width="80%" alt="VR Demo GIF"/>
---

## 1) 概述

XLeRobot是一个基于LeRobot的设置，添加了：
- **BiSO101Follower**（双臂follower arm）
- **BiSO101Leader**（双臂遥操作/leader arm）
- **独立**控制左/右臂 + **同步**双臂操作
- **三摄像头**记录配置：
  - `front_cam`
  - `hand_cam`
  - `side_cam`
 <img width="734" height="639" alt="image" src="https://github.com/user-attachments/assets/051b57fc-12ee-41a0-a2ff-78d207baa596" />


### 参考资料
- [SmolVLA基础模型](https://huggingface.co/lerobot/smolvla_base)
- [ACT文档](https://huggingface.co/docs/lerobot/en/act)
- [XLeRobot / LeRobot fork使用](https://github.com/kahowang/lerobot)
- [Rumi](https://github.com/MakerModsRobotics/Rumi)
- [XLeRobot改进升级](https://github.com/MakerModsRobotics/xlerobot_improvements)

---

## 2) 演示任务（SmolVLA可以用~20个episode学习什么）



### 演示1 - 抽屉 + 抓取 + 放置 + 抓握（双臂）
在训练**~20个episode**后，XLeRobot可以：
1. 拉开抽屉
2. 抓取物体
3. 将物体放入抽屉
4. 推入抽屉


<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/side-view.gif?raw=true" width="80%" alt="VR Demo GIF"/>

**关键方面：**
- **一次性抓取**抽屉把手（在数据收集期间避免抖动）
- 当**左臂**拉抽屉时，**右臂**必须**精确**抓取物体的中心
- **准确的一次性放置**到抽屉中并平滑地"推入"关闭

### 演示2 - 铅笔盒拉链（精细操作）
在训练**~20个episode**后，XLeRobot可以：
1. 抓取拉链拉片
2. 抓取铅笔盒把手并稳定盒子
3. 拉动拉链拉片以平滑打开拉链

<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/unzip-bagger.gif?raw=true" width="80%" alt="VR Demo GIF"/>

**关键难点：**
- 拉链拉片通常在**自上而下的摄像头盲点**中，需要**一次性**抓取（避免重新抓取）
- 保持一致的拉动高度以避免上下移动（没有"向上猛拉"或"向下拖拽"）

---

## 3) 硬件/配置说明

### 摄像头放置（三个摄像头）
推荐配置：
- `front_cam` × 1
- `hand_cam` × 1
- `side_cam` × 1

> **注意：**在实践中，一致的摄像头放置和稳定的照明对于学习稳定的操作至关重要。

### 动作维度处理（重要）
双臂SO-101机器人有**12个动作维度**：
- 6个关节 × 2个手臂 = **12**

**SmolVLA自动检测和处理动作维度**，无需手动配置：
- 训练期间：**12-D → 填充到32-D**（`max_action_dim`）
- 推理期间：**32-D → 裁剪回原始12-D**

**概念代码路径：**
```python
# 训练: 12D -> 填充到32D
actions = pad_vector(batch[ACTION], self.config.max_action_dim)

# 推理: 32D -> 裁剪回12D
original_action_dim = self.config.action_feature.shape[0]  # 自动检测: 12
actions = actions[:, :, :original_action_dim]
```

与其他可能需要手动`action_mode`配置的VLA模型（例如xVLA）不同，SmolVLA的动态填充支持任何≤32D的动作空间。

---

## 4) 安装和环境设置（Linux）

### A. 安装Miniconda（示例）
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh

# 重启终端，然后验证
conda --version
```

### B. 创建和激活环境
```bash
conda create -n lerobot python=3.10
conda activate lerobot
```

> **注意：**每次使用LeRobot/XLeRobot时都要激活此环境：
> ```bash
> conda activate lerobot
> ```

### C. 安装系统依赖（FFmpeg）
```bash
conda install -c conda-forge ffmpeg
```

### D. 克隆仓库并安装依赖
```bash
git clone https://github.com/kahowang/lerobot.git
cd lerobot

# 安装带Feetech电机支持的LeRobot（SO-101需要）
pip install -e ".[feetech]"

# 安装SmolVLA依赖
pip install -e ".[smolvla]"
```

---

## 5) 数据收集（三摄像头，双臂遥操作）

使用`lerobot-record`记录三摄像头的双臂演示。

将`${HF_USER}`和`your_dataset_name`替换为您的Hugging Face用户名和数据集名称。

```bash
lerobot-record \
  --robot.type=bi_so101_follower \
  --robot.left_arm_port=/dev/ttyACM0 \
  --robot.right_arm_port=/dev/ttyACM1 \
  --robot.id=bimanual_follower \
  --robot.cameras='{
    "front_cam": {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30},
    "hand_cam": {"type": "opencv", "index_or_path": 1, "width": 640, "height": 480, "fps": 30},
    "side_cam": {"type": "opencv", "index_or_path": 2, "width": 640, "height": 480, "fps": 30}
  }' \
  --teleop.type=bi_so101_leader \
  --teleop.left_arm_port=/dev/ttyACM2 \
  --teleop.right_arm_port=/dev/ttyACM3 \
  --teleop.id=bimanual_leader \
  --dataset.repo_id=${HF_USER}/your_dataset_name \
  --dataset.single_task="Your task description here" \
  --dataset.num_episodes=50
```

### 参数提示
1. 端口（`/dev/ttyACM*`）必须匹配您的实际USB设备映射
2. `dataset.single_task`应该简洁但具体（提高可重复性）
3. 为了快速迭代，从20个episode开始并逐步扩展

---

## 6) 训练策略

### 6.1) 训练SmolVLA

```bash
lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --dataset.repo_id=${HF_USER}/your_dataset_name \
  --batch_size=64 \
  --steps=20000 \
  --output_dir=outputs/train/smolvla_three_cameras \
  --job_name=smolvla_training_three_cameras \
  --policy.device=cuda \
  --wandb.enable=true
```

**说明：**
1. `--policy.path=lerobot/smolvla_base`指向SmolVLA基础策略
2. 根据数据集大小和任务复杂度调整`--steps`
3. 如果您没有GPU，设置`--policy.device=cpu`（训练会很慢）

### 6.2) 训练ACT (Action Chunking with Transformers)

ACT是一种模仿学习方法，预测短动作块而不是单步。它通常在使用遥操作数据时实现高成功率。

**基本训练命令：**
```bash
python -m lerobot.scripts.train \
  --dataset.repo_id=${HF_USER}/your_dataset_name \
  --policy.type=act \
  --output_dir=outputs/train/act_bimanual_demo \
  --job_name=act_training_bimanual \
  --policy.device=cuda \
  --policy.repo_id=${HF_USER}/act_bimanual_demo \
  --wandb.enable=true
```

**使用`lerobot-train`的替代方法：**
```bash
lerobot-train \
  --policy.type=act \
  --dataset.repo_id=${HF_USER}/your_dataset_name \
  --output_dir=outputs/train/act_bimanual_demo \
  --job_name=act_training_bimanual \
  --policy.device=cuda \
  --wandb.enable=true
```

**训练说明：**
- 检查点写入`outputs/train/<job_name>/checkpoints/`
- ACT通常在单个GPU上训练几个小时（~80M参数）
- 在Nvidia A100上，80k步的检查点大约需要1h45
- 对于Apple Silicon：使用`--policy.device=mps`

**从检查点恢复训练：**
```bash
python -m lerobot.scripts.train \
  --config_path=outputs/train/act_bimanual_demo/checkpoints/last/pretrained_model/train_config.json \
  --resume=true
```

---

## 7) 推理/评估

### 7.1) SmolVLA推理

运行策略推理并记录评估episode的典型模式：

```bash
lerobot-record \
  --robot.type=bi_so101_follower \
  --robot.left_arm_port=/dev/ttyACM0 \
  --robot.right_arm_port=/dev/ttyACM1 \
  --robot.id=bimanual_follower \
  --robot.cameras='{
    "front_cam": {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30},
    "hand_cam": {"type": "opencv", "index_or_path": 1, "width": 640, "height": 480, "fps": 30},
    "side_cam": {"type": "opencv", "index_or_path": 2, "width": 640, "height": 480, "fps": 30}
  }' \
  --dataset.single_task="Your task description here" \
  --dataset.repo_id=${HF_USER}/eval_results \
  --dataset.num_episodes=10 \
  --policy.path=${HF_USER}/smolvla_three_cameras
```

**说明：**
1. `--policy.path`应该指向您训练的策略检查点/上传的策略
2. `eval_results`是用于评估日志的单独数据集仓库（推荐）

### 7.2) ACT推理

**使用`lerobot-record`：**
```bash
lerobot-record \
  --robot.type=bi_so101_follower \
  --robot.left_arm_port=/dev/ttyACM0 \
  --robot.right_arm_port=/dev/ttyACM1 \
  --robot.id=bimanual_follower \
  --robot.cameras='{
    "front_cam": {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30},
    "hand_cam": {"type": "opencv", "index_or_path": 1, "width": 640, "height": 480, "fps": 30},
    "side_cam": {"type": "opencv", "index_or_path": 2, "width": 640, "height": 480, "fps": 30}
  }' \
  --dataset.single_task="Your task description here" \
  --dataset.repo_id=${HF_USER}/eval_act_results \
  --dataset.num_episodes=10 \
  --policy.path=${HF_USER}/act_bimanual_demo
```

**使用`python -m lerobot.record`：**
```bash
python -m lerobot.record \
  --robot.type=bi_so101_follower \
  --robot.left_arm_port=/dev/ttyACM0 \
  --robot.right_arm_port=/dev/ttyACM1 \
  --dataset.repo_id=${HF_USER}/eval_act_results \
  --policy.path=${HF_USER}/act_bimanual_demo \
  --episodes=10
```

**说明：**
- 策略将在机器人上自主执行
- 评估结果保存到指定的数据集仓库
- 将评估episode与训练演示进行比较以评估性能

---

## 8) XLeRobot的VR控制


<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/VR_DEMO_SHOW.gif?raw=true" width="80%" alt="VR Demo GIF"/>


### 机器人：Rumi
Rumi是一个具有可升降底盘的新一代双臂机器人：
[Rumi](https://www.makermods.ai/rumi)

![RUMI_HEAD_VR](https://github.com/user-attachments/assets/82b79de8-4286-4284-810f-b57308494bf0)

### 仓库
1. [VR控制器仓库](https://github.com/IIMFINE/lerobot_vr_controller.git)
2. [LeRobot仓库（fork）](https://github.com/IIMFINE/lerobot.git)

### 功能
1. VR → 机器人手臂映射
2. 支持：
   - 逆运动学（IK）求解
   - 关节空间 → 电机命令转换

### XLeRobot集成ROS 2
对于VR控制，请按照仓库的README配置VR设备、ROS 2节点和机器人驱动程序。

---

<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/VR_DEMO_SHOW2.gif?raw=true" width="80%" alt="VR Demo GIF"/>

## 9) 实用技巧/常见陷阱

### 数据质量
1. 在演示期间争取一次性抓取（避免微调）
2. 在记录和推理之间保持摄像头视角一致
3. 保持稳定的照明并避免运动模糊

### 双臂协调
对于抽屉等任务：
- **左臂：**稳定的拉动轨迹
- **右臂：**精确的抓取/放置，最小犹豫

<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/VR_DEMO_SHOW3.gif?raw=true" width="80%" alt="VR Demo GIF"/>

### 设备端口
如果端口在重启后更改，考虑使用持久的udev规则来稳定设备命名。
---

<img src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/VR_DEMO_SHOW4.gif?raw=true" width="80%" alt="VR Demo GIF"/>

## 10) 快速检查清单

- [ ] `conda activate lerobot`
- [ ] 三个摄像头已连接且索引正确（0/1/2）
- [ ] Follower端口正确（`/dev/ttyACM0`，`/dev/ttyACM1`）
- [ ] Leader端口正确（`/dev/ttyACM2`，`/dev/ttyACM3`）
- [ ] 数据集仓库ID和任务描述已设置
- [ ] 训练在正确的设备上运行（cuda vs cpu）
- [ ] 推理使用正确的训练策略路径

---

<video width="100%" controls>
  <source src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/makermod/makermod.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

## 附录：链接

### 官方文档
- [LeRobot文档](https://huggingface.co/docs/lerobot)
- [ACT文档](https://huggingface.co/docs/lerobot/en/act)
- [真实世界机器人的模仿学习](https://huggingface.co/docs/lerobot/il_robots)
- [真实世界机器人入门](https://huggingface.co/docs/lerobot/en/getting_started_real_world_robot)

### 模型和仓库
- [SmolVLA基础](https://huggingface.co/lerobot/smolvla_base)
- [ACT示例模型](https://huggingface.co/lerobot/act_aloha_sim_transfer_cube_human)
- [XLeRobot fork使用](https://github.com/kahowang/lerobot)
- [Rumi机器人](https://www.makermods.ai/rumi)
- [VR控制器](https://github.com/IIMFINE/lerobot_vr_controller.git)
- [LeRobot fork](https://github.com/IIMFINE/lerobot.git)

