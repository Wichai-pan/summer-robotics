## LLM Agent Control

Imagine telling the robot "go cleanup my kitchen" and watching it doing so. This tutorial will show you how you can make your XLeRobot fully autonomous, self-decision making machine by providing it with LLM agent. An agent that uses camera vision and voice commands to move the robot and manipulate objects with VLA policies.

Demo of agent controlling XLeRobot, that has a task to grab a notebook and give it to human:

<video width="100%" controls>
  <source src="https://vector-wangel.github.io/XLeRobot-assets/videos/Real_demos/agent_in_action.mov" type="video/mp4">
  Your browser does not support the video tag.
</video>

### Getting Started

To create our agent, we will use the [RoboCrew](https://github.com/Grigorij-Dudnik/RoboCrew) library - one specially designed for embodied agents. On your control device (Raspberry Pi or laptop) create a new virtual environment and install it with:

```bash
pip install robocrew
```

Next, create the python script to control your robot. Let's start by creating a simple agent that performs just one hardcoded task and finishes. 

First, let's initialize camera and create tools for agent to control a wheel movement:

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import create_move_forward, create_turn_right, create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler

# set up main camera
main_camera = RobotCamera("/dev/camera_center") # camera usb port Eg: /dev/video0

#set up servo controler
right_arm_wheel_usb = "/dev/arm_right"    # provide your right arm usb port. Eg: /dev/ttyACM1
servo_controler = ServoControler(right_arm_wheel_usb=right_arm_wheel_usb)

#set up tools
move_forward = create_move_forward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)
```

in place of `/dev/arm_right` you should provide the USB port name of your right arm (one connected to the wheels).

Next, let's initialize and run an agent itself:

```python
# init agent
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

In the code above we initialized our agent with the maneuver tools we created earlier. You can provide any model in LangChain notation. Next, we hard-coding a task for our agent and running it.

Before going to LLM, camera image is specially augmented to make it easier for robot to understand its environment: 

<div style="text-align: center; font-style: italic">
  <img src="https://github.com/user-attachments/assets/296f6f60-52a4-4fa0-9a77-a113b4868f83" width="60%">
  <p>That's how your robot sees the world.</p>
</div>

Also, create the `.env` file with parameter `GOOGLE_API_KEY=<your gemini api key here>` beside the script to connect to LLM.

Now run the code and watch your XLeRobot approaching you - then it will finish its work by calling `finish_task` tool!

Complete code is here:

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import create_move_forward, create_turn_right, create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler

# set up main camera
main_camera = RobotCamera("/dev/camera_center") # camera usb port Eg: /dev/video0

#set up servo controler
right_arm_wheel_usb = "/dev/arm_right"    # provide your right arm usb port. Eg: /dev/ttyACM1
left_arm_head_usb = "/dev/arm_left"      # provide your left arm usb port. Eg: /dev/ttyACM0
servo_controler = ServoControler(right_arm_wheel_usb, left_arm_head_usb)

#set up tools
move_forward = create_move_forward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)

# init agent
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[move_forward, turn_left, turn_right],
    main_camera=main_camera,
    servo_controler=servo_controler,
)

agent.task = "Approach a human."

agent.go()
```

### Set up Udev rules

Before proceeding to more advanced examples, let's do optional, but highly recommended step - make the usb port names for arms and cameras constant, to avoid swapping those names after every Raspberry Pi reboot. To do it, we need to set up udev rules. Luckily, RoboCrew already contains an utility that makes a complicated process of setting up udevs a matter of few clicks.

Run:

```bash
robocrew-setup-usb-modules
```

Utility will ask you to disconnect all usbs and then connect one after another - that way your usb devices will receive a constant names.

### Voice-conrolled agent

We managed to run our simple agent, now let's give it an ability to listen to our voice commands through the microphone.

First, we need to install Portaudio, to enable our control device to hear:

```bash
sudo apt install portaudio19-dev
```

Connect to your agent a soundcard with microphone, and optionally speaker, if you want robot to respond to you.

Let's change the agent initialization a little bit:

```python
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[move_forward, turn_left, turn_right],
    main_camera=main_camera,
    servo_controler=servo_controler,
    sounddevice_index=2,    # provide your microphone device index.
    wakeword="hey robot",   # optional - set up custom wakeword (default is "robot")
    tts=True,               # enable text-to-speech (robot can speak).
)

agent.go()
```

As you can see, we need to provide index of our soundcard with microphone. We can also set up a wakeword (default is "robot") - when robot hears that word in your sentence, it treats sentence as a new task; otherwise ignores it.

`tts=True` is needed if you want robot to speak.

We can also set up `history_len` - how many of last movements robot should keep in the memory, to avoid memory overflow.

Run the code and ask the robot to go somewhere!

Complete code is here:

```python
from robocrew.core.camera import RobotCamera
from robocrew.core.LLMAgent import LLMAgent
from robocrew.robots.XLeRobot.tools import create_move_forward, create_turn_right, create_turn_left
from robocrew.robots.XLeRobot.servo_controls import ServoControler

# set up main camera
main_camera = RobotCamera("/dev/camera_center") # camera usb port Eg: /dev/video0

#set up servo controler
right_arm_wheel_usb = "/dev/arm_right"    # provide your right arm usb port. Eg: /dev/ttyACM1
servo_controler = ServoControler(right_arm_wheel_usb=right_arm_wheel_usb)

#set up tools
move_forward = create_move_forward(servo_controler)
turn_left = create_turn_left(servo_controler)
turn_right = create_turn_right(servo_controler)

# init agent
agent = LLMAgent(
    model="google_genai:gemini-3-flash-preview",
    tools=[move_forward, turn_left, turn_right],
    main_camera=main_camera,
    servo_controler=servo_controler,
    sounddevice_index=2,    # provide your microphone device index.
    wakeword="hey robot",   # optional - set up custom wakeword (default is "robot")
    tts=True,               # enable text-to-speech (robot can speak).
)

agent.task = "Wait for the voice commands and execute."

agent.go()
```

### Activate arm manipulation

Let's go to the most advanced and useful part of our agent - the arms manipulation through VLA policies! That allows the robot to make full range of household tasks - like throwing out a trash or bringing you a tea from kitchen.

First of all, you need to train the policy agent will utilize later. Reference [VLA tutorial](https://xlerobot.readthedocs.io/en/latest/software/getting_started/VLA_ACT.html) to learn how to do it.

Let's assume you trained VLA policy that grabs a notebook from the table and put it in the robot basket (for further transportation). Let's add it as a tool for your agent:

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

Provide the tool with parameters your custom tool name and description - that's what LLM will see. Also, provide VLA-related parameters - as the name of your trained policy on HF hub, policy type, camera config (same you used during dataset collection).

Then add created `pick_up_notebook` tool to the tools of your agent. You can create as many manipulation tools as you want.

Our tool is a policy client, but all VLA computations are run on the server side. We need to run policy server - on Raspberry Pi only in case of light-weight ACT policy, on different computer for all other policies. Run your server with:

```
python -m lerobot.async_inference.policy_server \
     --host=0.0.0.0 \
     --port=8080
```

In case you using external computer in your local network as a server, provide its IP instead of zeros to `server_address` parameter like: `server_address="123.234.12.34:8080"`

That's it! Prompt your robot to grab a notebook from the table and give it to you!

In the full code, we also added more movement tools for more precision navigation:

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


# set up main camera
main_camera = RobotCamera("/dev/camera_center") # camera usb port Eg: /dev/video0

#set up servo controler
right_arm_wheel_usb = "/dev/arm_right"    # provide your right arm usb port. Eg: /dev/ttyACM1
left_arm_head_usb = "/dev/arm_left"      # provide your left arm usb port. Eg: /dev/ttyACM0
servo_controler = ServoControler(right_arm_wheel_usb, left_arm_head_usb)

#set up tools
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

# init agent
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