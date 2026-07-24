# Get Started

Here's the full video for keyboard EE control

<video width="100%" style="max-width: 100%;" controls>
  <source src="https://github.com/user-attachments/assets/b8e630bd-1133-4941-acd1-d974f60098ff" type="video/mp4">
  Your browser does not support the video tag.
</video>

### Prerequisites

- Ubuntu operating system
- Basic familiarity with terminal commands
- [Miniconda](https://docs.anaconda.com/free/miniconda/index.html) (recommended)

### Installation

#### 1. Create a Conda Environment

If you already have a `lerobot` conda environment, you can use that. Otherwise, create a new environment:

```bash
conda create -y -n lerobot python=3.10
conda activate lerobot

```

> Note: It's recommended to have ManiSkill and lerobot code in the same environment for future sim2real deployment.
> 

#### 2. Install ManiSkill

Follow the [official installation instructions](https://maniskill.readthedocs.io/en/latest/user_guide/getting_started/installation.html) for ManiSkill.

```bash
# Basic installation
pip install mani-skill

# Download scene dataset
python -m mani_skill.utils.download_asset "ReplicaCAD"

```

#### 2.1 If the dataset downloading goes wrong, use:

```bash
git clone <https://huggingface.co/datasets/haosulab/ReplicaCAD>

```

to directly download the dataset from huggingface. And then folder contents should go to

```bash
~/.maniskill/data/scene_datasets/replica_cad_dataset

```

#### 2.2 Familiarize yourself with ManiSkill using the [quickstart guide](https://maniskill.readthedocs.io/en/latest/user_guide/getting_started/quickstart.html) and [demo scripts](https://maniskill.readthedocs.io/en/latest/user_guide/getting_started/quickstart.html). 

Try this command to test whether you have successfully installed Maniskill:
```bash
python -m mani_skill.examples.demo_random_action -e "ReplicaCAD_SceneManipulation-v1" \\
  --render-mode="human" --shader="rt-fast"

```

And you should be looking at something like this:

![image](https://github.com/user-attachments/assets/c7509843-f037-4f37-9b1c-e7cad939037c)

#### 3. Additional Dependencies

```bash
pip install pygame
```

#### 4. Replace Robot Files

Navigate to the ManiSkill package folder in your conda environment:

```bash
cd ~/miniconda3/envs/lerobot/lib/python3.10/site-packages/mani_skill
```

Replace the fetch robot code and assets with the XLeRobot files:

1. Download simulation/Maniskill.zip
2. Replace the files in /agents and /assets:
    
    ![image](https://github.com/user-attachments/assets/2675fb26-0302-45ec-a994-d4133ce8c239)
    
    ![image](https://github.com/user-attachments/assets/5a85d244-b342-45f5-bfa3-72f1ce11c83a)
    
3. Add control code to /examples:
    
    ![image](https://github.com/user-attachments/assets/654556ab-473f-44d2-8ff7-107c346882c6)
    

##### Usage

> The name of the files may be slightly different, check and change if you need.


##### Joint Control

Run the joint control demo with:

```bash
python -m mani_skill.examples.XLeRobot_demo_joint_ctrl -e "ReplicaCAD_SceneManipulation-v1"   --render-mode="human" --shader="rt-fast" -c "pd_joint_delta_pos_dual_arm"

```

##### End Effector Control

Run the end effector control demo with:

```bash
python -m mani_skill.examples.XLeRobot_demo_ee_ctrl -e "ReplicaCAD_SceneManipulation-v1"   --render-mode="human" --shader="rt-fast" -c "pd_joint_delta_pos_dual_arm"

```

#### 5. Rename the links

If you encounter this error:

![image](https://github.com/user-attachments/assets/c81569a3-5c4f-4ba6-99d9-65d84937e767)

Navigate to the corresponding script

![image](https://github.com/user-attachments/assets/afda5567-3dfa-4e04-997f-4b5eff0dd1bc)

and change "torso_lift_link" to "head_camera_link"

![image](https://github.com/user-attachments/assets/05b52683-5e50-47fc-9cf7-9c021927db18) Before Printing 🤔

> We assume you have basic experience with consumer-level 3D printers (BambuLab, Prusa, etc.). This means you know how to properly 3D print STL files with PLA filaments and are familiar with reorienting parts, adding supports, adjusting infill, and modifying print speed to achieve your desired balance of material strength, efficiency, and model detail quality.
> 
- For more detailed information, you can check out the 3D printing instructions for [Lekiwi](https://github.com/SIGRobotics-UIUC/LeKiwi/blob/main/3DPrinting.md) and [SO100 Arm](https://github.com/TheRobotStudio/SO-ARM100#printing-the-parts).
- All the 3D printed parts shown in the demo videos and pictures of XLeRobot were printed with a **BambuLab A1 using BambuLab PLA Matte Black**.
- You can also use filaments with better mechanical properties, such as **PETG HF, PLA CF**, etc., to enhance the arm's strength.

An example comparison:

![image](https://github.com/user-attachments/assets/3d0eeb80-1fc6-47cb-bd15-bc2f023030f4)

## ⏫ Extra Parts for XLeRobot ⏫

If you already have 2 SO100 Arms and 1 Lekiwi base, you'll only need 3 additional parts for the XLeRobot hardware version 0.1.0.

(Please also check the Build From Scratch section below, as the parts list differs slightly)

### [Arm bases](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/XLeRobot_special/SO_5DOF_ARM100_Assemblybases.stl)

- The bases are designed to rotate 15 degrees outward, expanding the workspace area on both sides while enabling smooth collaboration between the two arms.
- <img src="https://github.com/user-attachments/assets/f612c9d8-fca2-406e-ab25-d015ea5e62c4" width="500" />
- The [original forward facing base](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/XLeRobot_special/XLe_arm_bases_0degrees_rotated.stl) is also available if you want to keep things simple.
- 
    
    ![image](https://github.com/user-attachments/assets/eb77aad3-4df3-45c1-93c2-1c2e278512b5)
    
- The design features a hollow center to save filament. You can insert a used Bambulab filament cardboard spool for added structural support.
- <img src="https://github.com/user-attachments/assets/384c5cb1-849c-43e5-a5e5-8f31d39712f8" width="300" />

### [Lekiwi base connectors](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/XLeRobot_special/BaseConnector.stl)

- This component connects the Lekiwi base's top plate to the IKEA cart bottom. It's an enhanced version of the Lekiwi base motor mount, redesigned for better stability.
- <img src="https://github.com/user-attachments/assets/07752338-1c1b-49ca-81b2-ccac9699b498" width="300" />

```{note}
If you're using a not an authentic IKEA cart, you can adjust the z-axis scale in your slicer software (while maintaining the xy-axis scale) to ensure even pressure distribution between the Lekiwi base and cart wheels.
```

### [Thinner Lekiwi base top plate](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/XLeRobot_special/base_plate_layer2_thinner.stl)

- This is a thinner version of the standard Lekiwi base top plate, used to secure the connectors to the IKEA cart bottom.
- <img src="https://github.com/user-attachments/assets/17d63ccf-469c-4811-860f-e55ffdee396b" width="400" />
- While the current connection between the Lekiwi base and cart is stable, an upcoming second version will simplify installation on the cart's metal mesh bottom.

## 🌿 Print from scratch 🌿

If you haven't printed any SO100 arm or Lekiwi base, follow their instructions ([Lekiwi](https://github.com/SIGRobotics-UIUC/LeKiwi/blob/main/3DPrinting.md) and [SO100 Arm](https://github.com/TheRobotStudio/SO-ARM100#printing-the-parts)) along with the suggestions below.

### 🦾 2x SO100 Arms

```{note}
As of April 28, 2025, the SO101 arm has been released with modifications to the follower arms model. These changes include simplified parts and improved wire management, while maintaining compatibility with XLeRobot. I highly suggest everyone build SO101 instead of SO100 since the assembly is much faster!
```
- In the current hardware version, you only need to print two [follower arms](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/SO100/Prusa_Follower_SO101.stl). The [leader arm](https://github.com/TheRobotStudio/SO-ARM100/tree/main/stl_files_for_3dprinting/Leader) is only necessary if you plan to operate the dual arms simultaneously with leader-follower joint control. Before printing, rearrange the layout of this stl file in the slicer software for your best printing experience.
- <img src="https://github.com/user-attachments/assets/a5a49a95-e75e-4ea1-879c-0a0ec22f07a7" width="800" />
- The Wrist Camera (MF) Mount and its [installation guide](https://github.com/TheRobotStudio/SO-ARM100/tree/main/Optional/Wrist_Cam_Mount_32x32_UVC_Module) for SO100 can help optimize data collection efficiency.
- <img src="https://github.com/user-attachments/assets/8f74f9f4-321c-4689-acbe-6d7280922bfe" width="400" />

### 🧑‍🦼‍➡️ Lekiwi Base

- For the Lekiwi base, you'll need to print: the [top](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/Lekiwi/base_plate_layer1.stl) and [bottom plates](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/Lekiwi/base_plate_layer2.stl), three [motor mounts](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/Lekiwi/drive_motor_mount_v2.stl), and three [wheel-servo hubs](https://www.notion.so/vectorwang/3D_Models/3D_models_for_printing/Lekiwi/servo_wheel_hub.stl). XLeRobot doesn't require any other parts.
- <img src="https://github.com/user-attachments/assets/7c35c7cc-ab69-4cf6-bfa9-0e4b3b983e22" width="800" />