# Dual wheel Assembly

Here briefly introduce how to build the dual wheel version.

(This page is still under construction)

## Intro
Main changes compared to 0.3.0:

- Dual wheel: More stable, higher moving speed, better passability, and larger torque (compared to 3 omni-wheels). 2 verisons: servo motors and brushless motors.
- Improved top base design: modular arm base with changable arm installing directions. 360 degree and compact head design.  

This 0.4.0 version of XLeRobot is the last version that is fully based on Feetech servo motors and the SO101 chassis. After extensive testing and research, we realized the limitations of servo motors (speed, noise, payload, etc.), and we believe this hardware version offers the best balance among cost, ease of assembly, stability, and practicality.

Regarding a lifting (height-adjustable) base, we have also explored related designs, but the maintenance difficulty and stability issues make it hard to achieve a good solution using only servo motors. For most development scenarios, mobility at desk height is already sufficient to support initial research and development needs. We also found that adding more degrees of freedom increases the difficulty of data collection and hurts policy generalization.

Going forward, we plan to collaborate with Hightorque and wowrobo to build more product-level, low-cost, open-source mobile robots based on higher-performance motors.


Official Assembly Videos from Wowrobo:
<iframe width="800" height="600" 
    src="https://www.youtube.com/embed/4bXCFw57T60" 
    frameborder="0" 
    allowfullscreen>
</iframe>

<iframe width="800" height="600" 
    src="//player.bilibili.com/player.html?bvid=BV1JpiqBfEuf&autoplay=0" 
    frameborder="0" 
    allowfullscreen>
</iframe>

### Servo motor version

Pros: 
- Compared to previous version: more stable, control is more accurate, less wiggle
- Compared to brushless version: still same servo motors, easier wiring and control

Cons:
- Compared to previous version: lose one Dof of moving left and right
- Compared to brushless version: still same servo motors, noisy, speed and torque not very high.

This can already be purchased at wowrobo. 

You can also buy parts yourself, what you need besides 3D printed parts and servo motors:

- Universal walker wheels (5 inches)
- 30 x 37 x 4mm Bearings
- longer Motor cables (or extension kit)

![image](https://github.com/user-attachments/assets/9d6f7c00-59b9-4999-a722-7fa8b5a56fdc)


Find STL file [Here](https://github.com/Vector-Wangel/XLeRobot/blob/main/hardware/XLeRobot_0_4_0_extra.stl)

![Animation (19)](https://github.com/user-attachments/assets/833d5e16-8d24-43dc-a5a5-fda023502cb1)
![Animation (18)](https://github.com/user-attachments/assets/766925b2-9fc2-4772-a936-55a78bebbe4c)


Assembled picture:

![image](https://github.com/user-attachments/assets/7e71afda-1ec5-4b96-a199-42a0cd726226)


### Brushless motor version

Build upon [Bracket Bot](https://www.bracket.bot/).

Find the connector to the IKEA cart [here](https://github.com/Vector-Wangel/XLeRobot/blob/main/hardware/Brushlessmotor%20connector.stl). (M8x20 screws required)

Pros: a fully stable and robust version with great performance.

Cons: more complex wiring.

![image](https://github.com/user-attachments/assets/f93b988c-6360-4bd9-a839-ea113a358fd4)


![Animation (20)](https://github.com/user-attachments/assets/b035c51c-3217-4666-8dc2-9285fbefaa09)

Still working on, release soon.
