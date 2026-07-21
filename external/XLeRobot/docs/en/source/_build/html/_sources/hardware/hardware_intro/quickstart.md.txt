# 🖨️ 3D printing

## 🤔 Before Printing 🤔

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