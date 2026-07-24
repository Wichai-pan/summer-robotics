# ⚒️ Assemble!

> Estimated Assembly time: From scratch: 2-4 hrs; with assembled SO100/SO101 arms: 1-2 hrs


## 🤔 Before Assembly 🤔

```{tip}
If you'd rather skip the fun of tightening screws (though every robot enthusiast should try it at least once), some companies sell [pre-assembled kits](https://github.com/TheRobotStudio/SO-ARM100#kits) for SO100/SO101 arms at a higher price.
```
- If you don't have assembled SO100/SO101 arms or Lekiwi: Please follow the instruction in [SO101 arm Repo](https://github.com/huggingface/lerobot/blob/main/examples/12_use_so101.md) to
    - [Install Lerobot on your PC](https://github.com/huggingface/lerobot/blob/main/examples/12_use_so101.md#install-lerobot)
- Configure the motors according to the [SO101](https://github.com/huggingface/lerobot/blob/main/examples/12_use_so101.md#configure-motors) and [LeKiwi](https://github.com/huggingface/lerobot/blob/main/examples/11_use_lekiwi.md#configure-motors) tutorials.
    - You need two sets of motors for 2 motor control boards: one for the SO101 arm (motors 1-6) and another for Lekiwi (motors 1-9).
    - Tips: write the numbers on motors with marker and distinguish motors for different boards (such as L1-L6 and R1-R6).

![image](https://github.com/user-attachments/assets/f3be78fe-0faa-454c-926d-ab1843b31d1f)

If you already have assembled and motor-configured SO100/SO101 arm and LeKiwi, you can skip the above steps.

## 🦾🦾 Assemble 2x SO101 Arms 🦾🦾

```{note}
As of April 28, 2025, the SO101 arm has been released with modifications to the follower arms model. These changes include simplified parts and improved wire management, while maintaining compatibility with XLeRobot. I highly suggest everyone build SO101 instead of SO100 since the assembly is much faster!
```
- If you already have 2x SO100/SO101 arms, skip.
- Build 2x SO101 arms by following [SO101 Step-by-Step Assembly Instructions](https://github.com/huggingface/lerobot/blob/main/examples/12_use_so101.md#step-by-step-assembly-instructions) to build 2 identical follower arms with 2 sets of motors (both preivous indexed as 1-6) for 2 control boards.
- If you also want to have the **Wrist Camera**, follow this [installation guide](https://github.com/TheRobotStudio/SO-ARM100/tree/main/Optional/Wrist_Cam_Mount_32x32_UVC_Module).
- If you have [3M gripper tape](https://www.amazon.com/gp/product/B0093CQPW8/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1), now it's time to wrap it on the fingers.

![image](https://github.com/user-attachments/assets/68cba2d4-9777-49bc-ad8a-b2931658c474)

```{tip}
Replace the motor's default cross-head screws with M3 hex screws—they're more durable, easier to install, and the black screws blend better with the black arm.
```

## 🧑‍🦼‍➡️ Assemble 1x Lekiwi Base 🧑‍🦼‍➡️

- If you already have a Lekiwi base, distach the battery, servo mounts, etc. Base plate will only have 3 mounted motors with wheels (keep the wirings).
    - If not, follow the [tutorial](https://github.com/SIGRobotics-UIUC/LeKiwi/blob/main/Assembly.md#2-bottom-plate-assembly) but also stop after mounting motors on the base plate with wheels.
    - No matter what, the simplified Lekiwi base should look like this:

![image](https://github.com/user-attachments/assets/1b0b0600-e666-4825-9233-807ed63e9020)

- Wiring the motors regularly as the [tutorial](https://github.com/SIGRobotics-UIUC/LeKiwi/blob/main/Assembly.md#2-bottom-plate-assembly), after that instead of connecting the wire to the control board, use the extended wire/connector kit to extend the wire, and leave it hanging (don't pull it out from the top plate just yet).

![image](https://github.com/user-attachments/assets/8d81267b-4b58-4af5-8bb3-e77b01d3df7f)

## 🛒 Install the IKEA RÅSKOG Cart 🛒

- Just in case you accidentally throw your manual away, [here it is](https://github.com/Vector-Wangel/XLeRobot/blob/main/others/Manuals_raskog_utility_cart.pdf).

<img width="925" alt="1745897734515" src="https://github.com/user-attachments/assets/f9f95840-5080-4084-bebb-ea456a097d55" />

## 🧑‍🦼‍➡️ Install the Lekiwi Base 🛒

- Mount the 3 [connectors](https://github.com/Vector-Wangel/XLeRobot/blob/main/3D_Models/3D_models_for_printing/XLeRobot_special/base_connector.stl) on the top plate, anywhere you think could give a stable support. Or just follow this:

[image](https://github.com/user-attachments/assets/c8233b2d-c58a-4ce5-8b25-b0e7832a60f3)

```{tip}
Put the Lekiwi base with the connectors under the cart to see whether it can give enough pressure to the cart, with four wheels of the cart can still touch the ground. If not, try to modify the connectors' 3D model by slightly adjust the z-axis scale directly in the slicer software (keeping the xy-axis scale unchanged) and print them again.
```

```{tip}
You might want to filp the cart over to do the assembly below.
```
- Now install the Lekiwi base with the connectors onto the bottom of the IKEA cart, with [the duplicated thinner top plate](https://github.com/Vector-Wangel/XLeRobot/blob/main/3D_Models/3D_models_for_printing/XLeRobot_special/base_plate_layer2_thinner.stl) on the other side.

```{note}
In the first version of hardware, it may be challenging to align all 3x4=12 screws perfectly. You can try to adjust the position and wiggle a little bit to find a place that can install the most screws distributed evenly. Currently the best I can do is 2 screws for each connector, which can give a very stable support. We will also update a new hardware version compatible with the IKEA cart metal mesh shortly.
```

```{note}
You should also refer to this figure (remade from Lekiwi tutorial) to find your desired assembly direction based on the motor index. Left and right are filpped becasuse it's down-top view.
```

![image](https://github.com/user-attachments/assets/35d4e60a-cf5a-46f1-8367-00e7990c27d3)


![image](https://github.com/user-attachments/assets/fe28320e-1851-495b-afc3-4e9302f92626)

- Use needle-nose pliers to cut out the metal mesh at the corresponding holes in the top base, removing only the central "x" to maintain structural integrity. This creates openings for cable routing. Then, run the previously extended wire up through the cart from below.

![image](https://github.com/user-attachments/assets/b30abce8-a12c-44c8-8e0b-ee720cc1b8fa)

## 🦾🦾 Install the Arms 🛒

- In the current version, for easier testing, the SO101 arms clamp directly onto the cart. Position the [arm bases](https://github.com/Vector-Wangel/XLeRobot/blob/main/3D_Models/3D_models_for_printing/XLeRobot_special/SO_5DOF_ARM100_Assemblybases.stl) at the two corners of the cart's top layer, then secure with clamps.
- Don't forget to put the bambulab filament cardboard spool inside to provide stable structural support.

![image](https://github.com/user-attachments/assets/daaa6731-8886-4770-8042-77a5a0afdb74)

![image](https://github.com/user-attachments/assets/46239c09-3d37-4115-8dbd-3438ee5b3bac)

- A second version will be released soon, featuring an option for bolted connection between the arms and the cart, with standardized spacing between the two arms.

```{note}
To test the basic single-arm version of XLeRobot directly with the original Lekiwi code before the code for XLeRobot is released, only clamp the SO101 arm that shares the same motor control board with the Lekiwi base. And clamp the other one on your table to act as the leader arm.
```

## 🔋 Place the Battery 🛒

- You can put it anywhere you like on the middle or lower level of the cart to maintain a low center of mass. The battery has an anti-slip bottom so it won't easily silde during normal operations.
    - I keep it on the middle level for shorter cable runs and easy access (for my 🥾hiking and 🏕️camping).
- Just in case you also accidentally throw the battery manual away, [here it is](https://github.com/Vector-Wangel/XLeRobot/blob/main/others/Manual_Anker_SOLIX_C300_DC_Portable_Power_Station.pdf).

![image](https://github.com/user-attachments/assets/c29b14c7-9bd7-45a9-bebd-8a7308a18a2a)

## 🧵 Last, Wiring 🧵

- Up til now, this is what XLeRobot should look like without the battery:

![image](https://github.com/user-attachments/assets/395e00c7-b8cf-4c4e-ac41-4b80c93c81a4)

- Use needle-nose pliers to cut out the metal mesh at for the upper two layers for cable routing the same way as the bottom layer previously. Choose the location as needed
    - I selected the middle of the back edge for minimal cable length and to avoid interfering with cart storage. Alternatively, you can route cables along the sides for a cleaner look.

<img width="843" alt="1745819677076" src="https://github.com/user-attachments/assets/ad081621-1e69-4bc6-a50f-d89cf92f35c3" />

- Prepare the extended 5264 wire with the connector kit if you don't have one already.

```{note}
When extending the 5264 wire yourself, be careful with the polarity—reversed connections will cause errors.
```
- Follow the wiring diagram below and:
    - Connect the extended 5264 **motor cable** from **the Lekiwi base** to **one of the SO101 arms** (this makes the base and the arm as Lekiwi).
    - Connect the 2 **USB-C to USB-A** **data cables** from 2 **motor control board** to **Rasberry Pi** (2 USB-A slots left for the cameras).
    - Connect all 3 **power cables**: 2 **USB-C to DC(12V)** from 2 **motor control board** and 1 **USB-C to USB-C** from **Rasberry Pi**, to the fast charging section of the power supply. Each slot provides up to 100W power when charging simultaneously, which is tested sufficient for 12V version operation.

```{important}
In order to protect the motor control board, make sure to connect the power cables last. And always disconnect the power cables when plugging/unplugging other cables.
```

```{note}
You need to install software on Rasberry Pi and setup SSH first before this final step.
```

![image](https://github.com/user-attachments/assets/5367eb11-377e-4243-a9ff-746266012901)

<img width="725" alt="1745906421978" src="https://github.com/user-attachments/assets/cfaf47d6-b112-4c89-93ce-cb2e21515ee0" />

```{important}
Once XLeRobot is fully assembled, do not push it around like the IKEA cart, as this can damage the motor gears. Instead, lift the robot (~12kg) whenever you need to move it manually.
```

### Finally, let's [🦾 Get Your Robot Moving! 🦿](https://www.notion.so/vectorwang/Software.md)

## XLeRobot Changelog

### Version 0.2.0 - Hardware Update Release

![image](https://github.com/user-attachments/assets/d17127c8-9025-4fab-bf48-c53a1c36e826)

#### 🔧 Hardware Updates

#### Bottom Base

- **Improved base plate layout**: All screws can now be installed smoothly without interference
- **Added branding**: XLeRobot (Zima) watermark and designer name have been added to the base plate

![image](https://github.com/user-attachments/assets/d3dc8614-ee42-4856-bd88-b1e6b3aacb76)

#### Top Base

- **Standardized arm spacing**: Two arm bases are now connected to ensure consistent spacing
    
    ![image](https://github.com/user-attachments/assets/4aed916e-5930-451c-ac72-795d2cb22601)
    
- **Clamp mounting system**: Retained clamp-based attachment for easier installation and modular design
    
    ![image](https://github.com/user-attachments/assets/03560435-1c14-42ac-8186-931a43eee0b5)
    
- **Integrated cable management**: Added protective shell for Raspberry Pi with organized cable routing
    
    ![image](https://github.com/user-attachments/assets/fff88e18-08ef-4165-bb0b-32affb557a99)
    
- **Hollow neck design**: Space-efficient design that saves filament while accommodating USB hub
    
    ![image](https://github.com/user-attachments/assets/95a7e585-e625-440e-90f9-5199c092aff7)
    
- **2-DOF head rotation**: Direct modification based on SO101 base design
    
    ![image](https://github.com/user-attachments/assets/6de3d78d-392d-4d82-b19d-0e11d1f6bb0f)
    
- **Modular architecture**: Even if head functionality isn't immediately needed, you can print and assemble everything below the neck first
<img width="868" alt="1749615226961" src="https://github.com/user-attachments/assets/d5685698-5f49-407e-a12a-5adc6dbc658a" />

#### 🔨 Assembly Instructions

#### Hardware Requirements

- Continue using M3 hex screws as in previous versions
- Bottom base assembly process remains the same as [version 0.1.0](https://github.com/Vector-Wangel/XLeRobot/blob/main/Assembly.md#%EF%B8%8F-install-the-lekiwi-base-)
    - The connectors have been redesigned. You may also need to adjust its height (by changing z axis scale in the 3D slicer software) to find the best size.

#### Top Base Assembly

Follow the assembly sequence shown in the diagram below (easier when filpped over):

![image](https://github.com/user-attachments/assets/1640d830-b7e9-474b-810d-070097fec59e)

![image](https://github.com/user-attachments/assets/885034a4-61f8-4d61-ab43-b88788b6058b)

![image](https://github.com/user-attachments/assets/e8a3c68f-9fe6-47da-9428-920e9658d58f)

![image](https://github.com/user-attachments/assets/14d305cb-c222-4641-81a4-682850ddbf37)

Then it should be the same as the first two steps of [SO101 arm assembly](https://huggingface.co/docs/lerobot/so101#joint-1).

```{note}
Complete all wiring and put the Raspberry Pi in its case before clamping the top base to the IKEA cart. (Also use 3D printing filament spools if you have one for enhanced structural support)
```

![image](https://github.com/user-attachments/assets/0fc95a4e-d4aa-48a5-944a-cc1a984c20b2)

Be careful not to break the case when you jam the IKEA cart edge into the case socket.

![image](https://github.com/user-attachments/assets/66818d5e-ae6e-4217-bf45-795109140359)

#### ⚡️ Wiring

The head motors wiring are the same as Lekiwi, only with 2 motors instead of three, connected to the other available arm motor control board. But be careful with the joint limits.

#### 📸 Final Assembly