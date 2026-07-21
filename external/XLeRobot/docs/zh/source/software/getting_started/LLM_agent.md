## LLM Agent 控制

想象一下告诉机器人"去清理我的厨房"并看着它执行。本教程将向您展示如何通过为XLeRobot提供LLM agent，使其成为完全自主、自主决策的机器。该agent使用摄像头视觉和语音命令来移动机器人，并使用VLA策略操作物体。

演示agent控制XLeRobot，任务是抓取笔记本并交给人类：

<video width="100%" controls>
  <source src="https://vector-wangel.github.io/XLeRobot-assets/videos/Real_demos/agent_in_action.mov" type="video/mp4">
  Your browser does not support the video tag.
</video>

### 开始使用

要创建我们的agent，我们将使用[RoboCrew](https://github.com/Grigorij-Dudnik/RoboCrew)库——一个专门为具身agent设计的库。在您的控制设备（树莓派或笔记本电脑）上创建一个新的虚拟环境并安装它：

```bash
pip install robocrew
```

接下来，创建用于控制机器人的python脚本。让我们从创建一个简单的agent开始，它只执行一个硬编码的任务然后完成。

首先，让我们初始化摄像头并创建用于agent控制轮子移动的工具：

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import create_move_forward, create_turn_right, create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler

# 设置主摄像头
main_camera = RobotCamera("/dev/camera_center") # 摄像头usb端口 例如: /dev/video0

#设置舵机控制器
right_arm_wheel_usb = "/dev/arm_right"    # 提供您的右臂usb端口。例如: /dev/ttyACM1
servo_controler = ServoControler(right_arm_wheel_usb=right_arm_wheel_usb)

#设置工具
move_forward = create_move_forward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)
```

您应该提供右臂的USB端口名称（连接到轮子的那个）来替代`/dev/arm_right`。

接下来，让我们初始化并运行agent本身：

```python
# 初始化agent
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[
        move_forward,
        turn_left,
        turn_right,
    ],
    main_camera=main_camera,
    servo_controler=servo_controler,
)

agent.task = "Approach a human."

agent.go()
```

在上面的代码中，我们使用之前创建的移动工具初始化了agent。您可以提供LangChain表示法中的任何模型。接下来，我们为agent硬编码一个任务并运行它。

在发送到LLM之前，摄像头图像经过特殊增强，使机器人更容易理解其环境：

<div style="text-align: center; font-style: italic">
  <img src="https://github.com/user-attachments/assets/296f6f60-52a4-4fa0-9a77-a113b4868f83" width="60%">
  <p>这就是您的机器人看到的世界。</p>
</div>

此外，在脚本旁边创建`.env`文件，参数为`GOOGLE_API_KEY=<your gemini api key here>`以连接到LLM。

现在运行代码，观看您的XLeRobot接近您——然后它将通过调用`finish_task`工具完成工作！

完整代码在这里：

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import create_move_forward, create_turn_right, create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler

# 设置主摄像头
main_camera = RobotCamera("/dev/camera_center") # 摄像头usb端口 例如: /dev/video0

#设置舵机控制器
right_arm_wheel_usb = "/dev/arm_right"    # 提供您的右臂usb端口。例如: /dev/ttyACM1
left_arm_head_usb = "/dev/arm_left"      # 提供您的左臂usb端口。例如: /dev/ttyACM0
servo_controler = ServoControler(right_arm_wheel_usb, left_arm_head_usb)

#设置工具
move_forward = create_move_forward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)

# 初始化agent
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[move_forward, turn_left, turn_right],
    main_camera=main_camera,
    servo_controler=servo_controler,
)

agent.task = "Approach a human."

agent.go()
```

### 设置Udev规则

在进行更高级的示例之前，让我们做一个可选但强烈推荐的步骤——使手臂和摄像头的usb端口名称保持恒定，以避免在每次树莓派重启后交换这些名称。要做到这一点，我们需要设置udev规则。幸运的是，RoboCrew已经包含了一个实用程序，使设置udev的复杂过程只需几次点击即可完成。

运行：

```bash
robocrew-setup-usb-modules
```

实用程序将要求您断开所有usb连接，然后逐个连接——这样您的usb设备将获得恒定的名称。

### 语音控制的agent

我们已经成功运行了简单的agent，现在让我们给它通过麦克风听取语音命令的能力。

首先，我们需要安装Portaudio，以使我们的控制设备能够听到：

```bash
sudo apt install portaudio19-dev
```

将带有麦克风的声卡连接到您的agent，如果需要机器人响应您，还可以选择连接扬声器。

让我们稍微改变一下agent的初始化：

```python
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[move_forward, turn_left, turn_right],
    main_camera=main_camera,
    servo_controler=servo_controler,
    sounddevice_index=2,    # 提供您的麦克风设备索引。
    wakeword="hey robot",   # 可选 - 设置自定义唤醒词（默认为"robot"）
    tts=True,               # 启用文本转语音（机器人可以说话）。
)

agent.go()
```

如您所见，我们需要提供带有麦克风的声卡索引。我们还可以设置唤醒词（默认为"robot"）——当机器人在您的句子中听到该词时，它会将句子视为新任务；否则会忽略它。

如果您希望机器人说话，需要`tts=True`。

我们还可以设置`history_len`——机器人应该在内存中保留多少最近的动作，以避免内存溢出。

运行代码并让机器人去某个地方！

完整代码在这里：

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import create_move_forward, create_turn_right, create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler

# 设置主摄像头
main_camera = RobotCamera("/dev/camera_center") # 摄像头usb端口 例如: /dev/video0

#设置舵机控制器
right_arm_wheel_usb = "/dev/arm_right"    # 提供您的右臂usb端口。例如: /dev/ttyACM1
servo_controler = ServoControler(right_arm_wheel_usb=right_arm_wheel_usb)

#设置工具
move_forward = create_move_forward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)

# 初始化agent
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[move_forward, turn_left, turn_right],
    main_camera=main_camera,
    servo_controler=servo_controler,
    sounddevice_index=2,    # 提供您的麦克风设备索引。
    wakeword="hey robot",   # 可选 - 设置自定义唤醒词（默认为"robot"）
    tts=True,               # 启用文本转语音（机器人可以说话）。
)

agent.task = "Wait for the voice commands and execute."

agent.go()
```

### 激活手臂操作

让我们进入agent最先进和最有用的部分——通过VLA策略进行手臂操作！这允许机器人执行全方位的家务任务——比如扔垃圾或从厨房给您端茶。

首先，您需要训练agent稍后将使用的策略。参考[VLA教程](https://xlerobot.readthedocs.io/en/latest/software/getting_started/VLA_ACT.html)了解如何操作。

让我们假设您训练了一个VLA策略，可以从桌子上抓取笔记本并将其放入机器人篮子中（用于进一步运输）。让我们将其添加为您agent的工具：

```python
from robocrew.robots.XLeRobot.tools import create_vla_single_arm_manipulation

pick_up_notebook = create_vla_single_arm_manipulation(
    tool_name="Grab_a_notebook",
    tool_description="Manipulation tool to grab a notebook from the table and put it to your basket.",
    task_prompt="Grab a notebook.",
    server_address="0.0.0.0:8080",
    policy_name="Grigorij/act_right-arm-grab-notebook-2",
    policy_type="act",
    arm_port=right_arm_wheel_usb,
    servo_controler=servo_controler,
    camera_config={"main": {"index_or_path": "/dev/camera_center"}, "right_arm": {"index_or_path": "/dev/camera_right"}},
    main_camera_object=main_camera,
    policy_device="cpu",
)
```

为工具提供自定义工具名称和描述参数——这就是LLM将看到的内容。此外，提供VLA相关参数——如您在HF hub上训练的策略名称、策略类型、摄像头配置（与数据集收集期间使用的相同）。

然后将创建的`pick_up_notebook`工具添加到agent的工具中。您可以创建任意数量的操作工具。

我们的工具是策略客户端，但所有VLA计算都在服务器端运行。我们需要运行策略服务器——仅在轻量级ACT策略的情况下在树莓派上运行，对于所有其他策略，需要在不同的计算机上运行。使用以下命令运行服务器：

```
python -m lerobot.async_inference.policy_server \
     --host=0.0.0.0 \
     --port=8080
```

如果您使用本地网络中的外部计算机作为服务器，请将其IP提供给`server_address`参数，而不是零，例如：`server_address="123.234.12.34:8080"`

就是这样！提示您的机器人从桌子上抓取笔记本并交给您！

在完整代码中，我们还添加了更多移动工具以实现更精确的导航：

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import \
    create_vla_single_arm_manipulation, \
    create_go_to_precision_mode, \
    create_go_to_normal_mode, \
    create_move_backward, \
    create_move_forward, \
    create_strafe_right, \
    create_strafe_left, \
    create_look_around, \
    create_turn_right, \
    create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler


# 设置主摄像头
main_camera = RobotCamera("/dev/camera_center") # 摄像头usb端口 例如: /dev/video0

#设置舵机控制器
right_arm_wheel_usb = "/dev/arm_right"    # 提供您的右臂usb端口。例如: /dev/ttyACM1
left_arm_head_usb = "/dev/arm_left"      # 提供您的左臂usb端口。例如: /dev/ttyACM0
servo_controler = ServoControler(right_arm_wheel_usb, left_arm_head_usb)

#设置工具
move_forward = create_move_forward(servo_controler)
move_backward = create_move_backward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)
strafe_left = create_strafe_left(servo_controler)
strafe_right = create_strafe_right(servo_controler)

look_around = create_look_around(servo_controler, main_camera)
go_to_precision_mode = create_go_to_precision_mode(servo_controler)
go_to_normal_mode = create_go_to_normal_mode(servo_controler)

pick_up_notebook = create_vla_single_arm_manipulation(
    tool_name="Grab_a_notebook",
    tool_description="Manipulation tool to grab a notebook from the table and put it to your basket.",
    task_prompt="Grab a notebook.",
    server_address="0.0.0.0:8080",
    policy_name="Grigorij/act_right-arm-grab-notebook-2",
    policy_type="act",
    arm_port=right_arm_wheel_usb,
    servo_controler=servo_controler,
    camera_config={"main": {"index_or_path": "/dev/camera_center"}, "right_arm": {"index_or_path": "/dev/camera_right"}},
    main_camera_object=main_camera,
    policy_device="cpu",
)

give_notebook = create_vla_single_arm_manipulation(
    tool_name="Give_a_notebook_to_a_human",
    tool_description="Manipulation tool to take a notebook from your basket and give it to human.",
    task_prompt="Grab a notebook and give it to a human.",
    server_address="0.0.0.0:8080",
    policy_name="Grigorij/act_right_arm_give_notebook",
    policy_type="act",
    arm_port=right_arm_wheel_usb,
    servo_controler=servo_controler,
    camera_config={"main": {"index_or_path": "/dev/camera_center"}, "right_arm": {"index_or_path": "/dev/camera_right"}},
    main_camera_object=main_camera,
    policy_device="cpu",
    execution_time=45,
)

# 初始化agent
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    system_prompt=system_prompt,
    tools=[
        move_forward,
        move_backward,
        strafe_left,
        strafe_right,
        turn_left,
        turn_right,
        look_around,
        go_to_precision_mode,
        go_to_normal_mode,
        pick_up_notebook,
        give_notebook,
    ],
    history_len=8,
    main_camera=main_camera,
    camera_fov=90,
    servo_controler=servo_controler,
    debug_mode=True,
)

agent.task = "Approach blue notebook, grab it from the table and give it to human. Do not approach human until you grabbed a notebook."

agent.go()
```

