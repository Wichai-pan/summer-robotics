import gymnasium as gym
import numpy as np
import sapien
import pygame
import time
import math
import cv2
from PIL import Image
import torch

from mani_skill.envs.sapien_env import BaseEnv
from mani_skill.utils import gym_utils
from mani_skill.utils.wrappers import RecordEpisode


import tyro
from dataclasses import dataclass
from typing import List, Optional, Annotated, Union

@dataclass
class Args:
    env_id: Annotated[str, tyro.conf.arg(aliases=["-e"])] = "ReplicaCAD_SceneManipulation-v1"
    """The environment ID of the task you want to simulate"""

    obs_mode: Annotated[str, tyro.conf.arg(aliases=["-o"])] = "sensor_data"
    """Observation mode - changed to sensor_data to get camera images"""

    robot_uids: Annotated[Optional[str], tyro.conf.arg(aliases=["-r"])] = "xlerobot"
    """Robot UID(s) to use. Can be a comma separated list of UIDs or empty string to have no agents. If not given then defaults to the environments default robot"""

    sim_backend: Annotated[str, tyro.conf.arg(aliases=["-b"])] = "auto"
    """Which simulation backend to use. Can be 'auto', 'cpu', 'gpu'"""

    reward_mode: Optional[str] = None
    """Reward mode"""

    num_envs: Annotated[int, tyro.conf.arg(aliases=["-n"])] = 1
    """Number of environments to run."""

    control_mode: Annotated[Optional[str], tyro.conf.arg(aliases=["-c"])] = "pd_joint_delta_pos"
    """Control mode"""

    render_mode: str = "human"
    """Render mode - using human to get interactive rendering"""

    shader: str = "default"
    """Change shader used for all cameras in the environment for rendering. Default is 'minimal' which is very fast. Can also be 'rt' for ray tracing and generating photo-realistic renders. Can also be 'rt-fast' for a faster but lower quality ray-traced renderer"""

    record_dir: Optional[str] = None
    """Directory to save recordings"""

    pause: Annotated[bool, tyro.conf.arg(aliases=["-p"])] = False
    """If using human render mode, auto pauses the simulation upon loading"""

    quiet: bool = False
    """Disable verbose output."""

    seed: Annotated[Optional[Union[int, List[int]]], tyro.conf.arg(aliases=["-s"])] = None
    """Seed(s) for random actions and simulator. Can be a single integer or a list of integers. Default is None (no seeds)"""

def get_mapped_joints(robot):
    """
    Get the current joint positions from the robot and map them correctly to the target joints.
    
    The mapping for single arm control (10 joints):
    - full_joints[0,2] → current_joints[0,1] (base x position and base rotation)
    - full_joints[3,5,7,8,9] → current_joints[2,3,4,5,6] (arm joints)
    - full_joints[10] → current_joints[7] (gripper)
    - full_joints[4,6] → current_joints[8,9] (head joints)
    
    Returns:
        np.ndarray: Mapped joint positions with shape matching the target_joints
    """
    if robot is None:
        return np.zeros(10)  # Default size for action
        
    # Get full joint positions
    full_joints = robot.get_qpos()
    
    # Convert tensor to numpy array if needed
    if hasattr(full_joints, 'numpy'):
        full_joints = full_joints.numpy()
    
    # Handle case where it's a 2D tensor/array
    if full_joints.ndim > 1:
        full_joints = full_joints.squeeze()
    
    # Create the mapped joints array with correct size
    mapped_joints = np.zeros(10)
    


    # Base joints: [0,2] → [0,1]
    mapped_joints[8] = full_joints[0]  # Base X position
    mapped_joints[9] = full_joints[2]  # Base rotation
    
    # First arm: [3,6,9,11,13] → [2,3,4,5,6]
    mapped_joints[0] = full_joints[3]
    mapped_joints[1] = full_joints[6]
    mapped_joints[2] = full_joints[9]
    mapped_joints[3] = full_joints[11]
    mapped_joints[4] = full_joints[13]
    
    mapped_joints[5] = full_joints[15]

    mapped_joints[6] = full_joints[5]
    mapped_joints[7] = full_joints[8]
    
    return mapped_joints

def inverse_kinematics(x, y, l1=0.1159, l2=0.1350):
    """
    Calculate inverse kinematics for a 2-link robotic arm, considering joint offsets
    
    Parameters:
        x: End effector x coordinate
        y: End effector y coordinate
        l1: Upper arm length (default 0.1159 m)
        l2: Lower arm length (default 0.1350 m)
        
    Returns:
        joint2, joint3: Joint angles in radians as defined in the URDF file
    """
    # Calculate joint2 and joint3 offsets in theta1 and theta2
    theta1_offset = math.atan2(0.028, 0.11257)  # theta1 offset when joint2=0
    theta2_offset = math.atan2(0.0052, 0.1349) + theta1_offset  # theta2 offset when joint3=0
    
    # Calculate distance from origin to target point
    r = math.sqrt(x**2 + y**2)
    r_max = l1 + l2  # Maximum reachable distance
    
    # If target point is beyond maximum workspace, scale it to the boundary
    if r > r_max:
        scale_factor = r_max / r
        x *= scale_factor
        y *= scale_factor
        r = r_max
    
    # If target point is less than minimum workspace (|l1-l2|), scale it
    r_min = abs(l1 - l2)
    if r < r_min and r > 0:
        scale_factor = r_min / r
        x *= scale_factor
        y *= scale_factor
        r = r_min
    
    # Use law of cosines to calculate theta2
    cos_theta2 = -(r**2 - l1**2 - l2**2) / (2 * l1 * l2)
    
    # Calculate theta2 (elbow angle)
    theta2 = math.pi - math.acos(cos_theta2)
    
    # Calculate theta1 (shoulder angle)
    beta = math.atan2(y, x)
    gamma = math.atan2(l2 * math.sin(theta2), l1 + l2 * math.cos(theta2))
    theta1 = beta + gamma
    
    # Convert theta1 and theta2 to joint2 and joint3 angles
    joint2 = theta1 + theta1_offset
    joint3 = theta2 + theta2_offset
    
    # Ensure angles are within URDF limits
    joint2 = max(-0.1, min(3.45, joint2))
    joint3 = max(-0.2, min(math.pi, joint3))
    
    return joint2, joint3

def convert_tensor_to_numpy_image(tensor_image):
    """Convert tensor image to numpy array for display"""
    # Handle PyTorch tensors
    if hasattr(tensor_image, 'cpu'):
        # Move tensor to CPU first if it's on GPU
        tensor_image = tensor_image.cpu()
    
    if hasattr(tensor_image, 'numpy'):
        image = tensor_image.numpy()
    else:
        image = tensor_image
    
    # Handle different image formats
    if image.dtype == np.float32 or image.dtype == np.float64:
        # Normalize to 0-255 range
        if image.max() <= 1.0:
            image = (image * 255).astype(np.uint8)
        else:
            image = image.astype(np.uint8)
    else:
        image = image.astype(np.uint8)
    
    # Remove batch dimension if present
    if image.ndim == 4:
        image = image[0]  # Take first batch
    
    # Convert RGBA to RGB if needed
    if image.shape[-1] == 4:
        image = image[..., :3]
    
    return image

def main(args: Args):
    pygame.init()
    
    # Calculate screen size for control panel only (no camera display)
    control_panel_width = 600
    screen_width = control_panel_width + 20
    screen_height = 750  # Fixed height for control panel
    
    screen = pygame.display.set_mode((screen_width, screen_height))
    pygame.display.set_caption("Control Window - Use keys to move")
    font = pygame.font.SysFont(None, 24)
    
    np.set_printoptions(suppress=True, precision=3)
    verbose = not args.quiet
    if isinstance(args.seed, int):
        args.seed = [args.seed]
    if args.seed is not None:
        np.random.seed(args.seed[0])
    parallel_in_single_scene = args.render_mode == "human"
    if args.render_mode == "human" and args.obs_mode in ["sensor_data", "rgb", "rgbd", "depth", "point_cloud"]:
        print("Disabling parallel single scene/GUI render as observation mode is a visual one. Change observation mode to state or state_dict to see a parallel env render")
        parallel_in_single_scene = False
    if args.render_mode == "human" and args.num_envs == 1:
        parallel_in_single_scene = False
    env_kwargs = dict(
        obs_mode=args.obs_mode,
        reward_mode=args.reward_mode,
        control_mode=args.control_mode,
        render_mode=args.render_mode,
        sensor_configs=dict(shader_pack=args.shader),
        human_render_camera_configs=dict(shader_pack=args.shader),
        viewer_camera_configs=dict(shader_pack=args.shader),
        num_envs=args.num_envs,
        sim_backend=args.sim_backend,
        enable_shadow=True,
        parallel_in_single_scene=parallel_in_single_scene,
    )
    if args.robot_uids is not None:
        env_kwargs["robot_uids"] = tuple(args.robot_uids.split(","))
        if len(env_kwargs["robot_uids"]) == 1:
            env_kwargs["robot_uids"] = env_kwargs["robot_uids"][0]
    env: BaseEnv = gym.make(
        args.env_id,
        **env_kwargs
    )
    record_dir = args.record_dir
    if record_dir:
        record_dir = record_dir.format(env_id=args.env_id)
        env = RecordEpisode(env, record_dir, info_on_video=False, save_trajectory=False, max_steps_per_video=gym_utils.find_max_episode_steps_value(env))

    if verbose:
        print("Observation space", env.observation_space)
        print("Action space", env.action_space)
        if env.unwrapped.agent is not None:
            print("Control mode", env.unwrapped.control_mode)
        print("Reward mode", env.unwrapped.reward_mode)

    obs, _ = env.reset(seed=args.seed, options=dict(reconfigure=True))
    if args.seed is not None and env.action_space is not None:
            env.action_space.seed(args.seed[0])
    if args.render_mode is not None:
        viewer = env.render()
        if isinstance(viewer, sapien.utils.Viewer):
            viewer.paused = args.pause
        env.render()
    
    action = env.action_space.sample() if env.action_space is not None else None
    action = np.zeros_like(action)
    
    # Initialize target joint positions with zeros
    target_joints = np.zeros_like(action)
    target_joints[3] = 0.303
    target_joints[4] = 0.556
    target_joints[6] = 1.57  # Set wrist roll joint

    # Initialize end effector positions for both arms
    initial_ee_pos_arm1 = np.array([0.162, 0.118])  # Initial position for first arm

    ee_pos_arm1 = initial_ee_pos_arm1.copy()

    
    # Initialize pitch adjustment for end effector orientation
    initial_pitch_1 = 0.0  # Initial pitch adjustment for arm
    pitch_1 = initial_pitch_1
    pitch_step = 0.02  # Step size for pitch adjustment
    
    # Define tip length for vertical position compensation
    tip_length = 0.108  # Length from wrist to end effector tip
    
    # Define the step size for changing target joints and end effector positions
    joint_step = 0.01
    ee_step = 0.005  # Step size for end effector position control
    
    # Define the gain for the proportional controller as a list for each joint
    p_gain = np.ones_like(action)  # Default all gains to 1.0
    # Specific gains can be adjusted here
    p_gain[9] = 2     # Base forward/backward
    p_gain[0] = 0.5     # Base rotation - lower gain for smoother turning
    p_gain[1:5] = 1.0   # Arm joints
    p_gain[5] = 0.05  # Gripper joint
    p_gain[6] = 2  # Head pan
    p_gain[7] = 2  # Head tilt
    
    # Get initial joint positions if available
    current_joints = np.zeros_like(action)
    print("current_joints", current_joints)
    robot = None
    
    # Try to get the robot instance for direct access
    if hasattr(env.unwrapped, "agent"):
        robot = env.unwrapped.agent.robot
    elif hasattr(env.unwrapped, "agents") and len(env.unwrapped.agents) > 0:
        robot = env.unwrapped.agents[0]  # Get the first robot if multiple exist
    
    print("robot", robot)
    
    # Get the correctly mapped joints
    current_joints = get_mapped_joints(robot)
    
    # Ensure target_joints is a numpy array with the same shape as current_joints
    target_joints = np.zeros_like(current_joints)
    target_joints[4] = 1.57  # Set wrist roll
    
    # Set initial joint positions based on inverse kinematics from initial end effector position
    try:
        target_joints[1], target_joints[2] = inverse_kinematics(ee_pos_arm1[0], ee_pos_arm1[1])
    except Exception as e:
        print(f"Error calculating initial inverse kinematics: {e}")
    
    # Force second arm to fixed position in qpos immediately
    if robot is not None:
        current_qpos = robot.get_qpos()
        if hasattr(current_qpos, 'clone'):
            new_qpos = current_qpos.clone()
        else:
            new_qpos = current_qpos.copy()
        
        if len(new_qpos.shape) > 1:
            new_qpos = new_qpos.squeeze()
        
        if len(new_qpos) >= 17:
            # Set second arm to folded/safe position
            new_qpos[4] = 0.0    # Rotation_2 
            new_qpos[7] = 3.14   # Pitch_2 (folded back)
            new_qpos[10] = 3.14  # Elbow_2 (folded)
            new_qpos[12] = 0.0   # Wrist_Pitch_2
            new_qpos[14] = 1.57  # Wrist_Roll_2
            new_qpos[16] = 0.0   # Jaw_2 (gripper closed)
            
            robot.set_qpos(new_qpos)
            print("Second arm set to fixed position")
    
    # Add step counter for warmup phase
    step_counter = 0
    warmup_steps = 50
    
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                env.close()
                return
            elif event.type == pygame.KEYDOWN:
                # Reset all positions when 'x' is pressed (changed from 'r' since 'r' is now used for head control)
                if event.key == pygame.K_x:
                    # Reset end effector positions
                    ee_pos_arm1 = initial_ee_pos_arm1.copy()
                    
                    # Reset pitch adjustments
                    pitch_1 = initial_pitch_1
                    
                    # Reset target joints
                    target_joints = np.zeros_like(target_joints)
                    
                    # Calculate initial joint positions based on inverse kinematics
                    try:
                        compensated_y1 = ee_pos_arm1[1] - tip_length * math.sin(pitch_1)
                        target_joints[1], target_joints[2] = inverse_kinematics(ee_pos_arm1[0], compensated_y1)
                        
                                               
                        # Apply pitch adjustment to joint 5 and 10
                        target_joints[3] = target_joints[1] - target_joints[2] + pitch_1
                    except Exception as e:
                        print(f"Error calculating inverse kinematics during reset: {e}")
                    
                    print("All positions reset to initial values")
        
        keys = pygame.key.get_pressed()
        
        # Update target joint positions based on key presses - only after warmup
        if step_counter >= warmup_steps:
            # Base forward/backward - direct control
            if keys[pygame.K_w]:
                action[8] = 0.1  # Forward
            elif keys[pygame.K_s]:
                action[8] = -0.1  # Backward
            else:
                action[8] = 0.0  # Stop forward/backward movement
                
            # Base turning - using target_joints and P control
            if keys[pygame.K_a]:
                target_joints[9] += joint_step*2  # Turn left
            elif keys[pygame.K_d]:
                target_joints[9] -= joint_step*2  # Turn right
            
            # # Handle base rotation wraparound - if rotation falls below -π, add 2π
            # if target_joints[1] < -math.pi*1.01:
            #     target_joints[1] += 2 * math.pi
            # # If rotation exceeds π, subtract 2π
            # elif target_joints[1] > math.pi*1.01:
            #     target_joints[1] -= 2 * math.pi
            
            # Arm control - using end effector positions and inverse kinematics
            # First arm end effector control
            if keys[pygame.K_8]:  # Move end effector up
                ee_pos_arm1[1] += ee_step
                ee_changed_arm1 = True
            if keys[pygame.K_u]:  # Move end effector down
                ee_pos_arm1[1] -= ee_step
                ee_changed_arm1 = True
            if keys[pygame.K_9]:  # Move end effector forward
                ee_pos_arm1[0] += ee_step
                ee_changed_arm1 = True
            if keys[pygame.K_i]:  # Move end effector backward
                ee_pos_arm1[0] -= ee_step
                ee_changed_arm1 = True
                
            # Calculate inverse kinematics for first arm if end effector position changed
            compensated_y = ee_pos_arm1[1] + tip_length * math.sin(pitch_1)
            target_joints[1], target_joints[2] = inverse_kinematics(ee_pos_arm1[0], compensated_y)

            
            # Direct joint control for remaining joints of first arm
            if keys[pygame.K_7]:
                target_joints[0] += joint_step
            if keys[pygame.K_y]:
                target_joints[0] -= joint_step
                
            # Pitch control for first arm
            if keys[pygame.K_0]:
                pitch_1 += pitch_step
            if keys[pygame.K_o]:
                pitch_1 -= pitch_step
                
            # Apply pitch adjustment to joint 5 based on joints 3 and 4
            target_joints[3] = target_joints[1] - target_joints[2] + pitch_1
            
            # Wrist control for first arm
            if keys[pygame.K_MINUS]:
                target_joints[4] += joint_step*3
            if keys[pygame.K_p]:
                target_joints[4] -= joint_step*3
            
            
            # Gripper control - toggle between open and closed
            if keys[pygame.K_v]:
                # Toggle gripper (index 7)
                if target_joints[5] < 0.4:  # If closed or partially closed
                    target_joints[5] = 2.5  # Open
                else:
                    target_joints[5] = 0.1  # Close
                # Add a small delay to prevent multiple toggles
                pygame.time.delay(200)
                
            
            
            # Head motor control - set target positions
            if keys[pygame.K_r]:
                # Control head pan (index 8) - increase target position
                target_joints[6] += joint_step*2
            if keys[pygame.K_t]:
                # Control head pan (index 8) - decrease target position
                target_joints[6] -= joint_step*2
            if keys[pygame.K_f]:
                # Control head tilt (index 9) - increase target position
                target_joints[7] += joint_step*2
            if keys[pygame.K_g]:
                # Control head tilt (index 9) - decrease target position
                target_joints[7] -= joint_step*2
        
        # Get current joint positions using our mapping function
        current_joints = get_mapped_joints(robot)
        
        # # Handle base rotation wraparound for current joints too
        # if current_joints[1] < -math.pi:
        #     current_joints[1] += 2 * math.pi
        # elif current_joints[1] > math.pi:
        #     current_joints[1] -= 2 * math.pi
        
        # Simple P controller for joints (excluding base X which is directly controlled)
        if step_counter < warmup_steps:
            # During warmup, zero all actions except base movements which are handled above
            if len(action) >= 10:
                for i in range(0, 10):  # Skip base X (index 0)
                    action[i] = 0.0
        else:
            # Apply P control to joints 1-9 (base rotation, arm, gripper, head)
            # Base X (index 0) is controlled directly above
            if len(action) >= 10:
                for i in range(0, 10):
                    if i == 8:
                        continue
                    action[i] = p_gain[i] * (target_joints[i] - current_joints[i])
        
        # Clip actions to be within reasonable bound
        
        screen.fill((0, 0, 0))
        
        # Draw control panel
        control_panel_x = 10
        text = font.render("Controls:", True, (255, 255, 255))
        screen.blit(text, (control_panel_x + 10, 10))
        
        # Add warmup status to display
        if step_counter < warmup_steps:
            warmup_text = font.render(f"WARMUP: {step_counter}/{warmup_steps} steps", True, (255, 0, 0))
            screen.blit(warmup_text, (control_panel_x + 300, 10))
        
        control_texts = [
            "W/S: Base Forward/Back",
            "A/D: Base Rotation (+/-)",
            "Y/7: Arm Rotation (+/-)",
            "8/U: End Effector Up/Down",
            "9/I: End Effector Forward/Back",
            "0/O: Pitch Adjustment (+/-)",
            "-/P: Wrist Roll (+/-)",
            "V: Toggle Gripper",
            "R/T: Head Pan (+/-)",
            "F/G: Head Tilt (+/-)",
            "X: Reset all positions"
        ]
        
        col_height = len(control_texts) // 2 + len(control_texts) % 2
        for i, txt in enumerate(control_texts):
            col = 0 if i < col_height else 1
            row = i if i < col_height else i - col_height
            ctrl_text = font.render(txt, True, (255, 255, 255))
            screen.blit(ctrl_text, (control_panel_x + 10 + col * 200, 40 + row * 25))
        
        # Display full joints (before mapping)
        y_pos = 40 + col_height * 30 + 10
        
        # Get full joint positions
        full_joints = robot.get_qpos() if robot is not None else np.zeros(11)
        
        # Convert tensor to numpy array if needed
        if hasattr(full_joints, 'numpy'):
            full_joints = full_joints.numpy()
        
        # Handle case where it's a 2D tensor/array
        if full_joints.ndim > 1:
            full_joints = full_joints.squeeze()
            
        # Display full joints in one row (for single arm)
        full_joints_text = font.render(
            f"Full Joints (0-10): {np.round(full_joints[:11], 2)}", 
            True, (255, 150, 0)
        )
        screen.blit(full_joints_text, (control_panel_x + 10, y_pos))
        y_pos += 30
        
        # Display current joint positions in logical groups
        # Group 1: Base control [0,1]
        base_joints = current_joints[0:2]
        base_text = font.render(
            f"Base [0,1]: {np.round(base_joints, 2)}", 
            True, (255, 255, 0)
        )
        screen.blit(base_text, (control_panel_x + 10, y_pos))
        
        # Group 2: Arm [2,3,4,5,6]
        y_pos += 25
        arm_joints = current_joints[2:7]
        arm_text = font.render(
            f"Arm [2,3,4,5,6]: {np.round(arm_joints, 2)}", 
            True, (255, 255, 0)
        )
        screen.blit(arm_text, (control_panel_x + 10, y_pos))
        
        # Group 3: Gripper and Head [7,8,9]
        y_pos += 25
        other_joints = current_joints[7:10]
        other_text = font.render(
            f"Gripper+Head [7,8,9]: {np.round(other_joints, 2)}", 
            True, (255, 255, 0)
        )
        screen.blit(other_text, (control_panel_x + 10, y_pos))
        
        # Display target joint positions in logical groups
        y_pos += 35
        
        # Group 1: Base control [0,1]
        base_targets = target_joints[0:2]
        base_target_text = font.render(
            f"Base Target [0,1]: {np.round(base_targets, 2)}", 
            True, (0, 255, 0)
        )
        screen.blit(base_target_text, (control_panel_x + 10, y_pos))
        
        # Group 2: Arm [2,3,4,5,6]
        y_pos += 25
        arm_targets = target_joints[2:7]
        arm_target_text = font.render(
            f"Arm Target [2,3,4,5,6]: {np.round(arm_targets, 2)}", 
            True, (0, 255, 0)
        )
        screen.blit(arm_target_text, (control_panel_x + 10, y_pos))
        
        # Group 3: Gripper and Head [7,8,9]
        y_pos += 25
        other_targets = target_joints[7:10]
        other_target_text = font.render(
            f"Gripper+Head Target [7,8,9]: {np.round(other_targets, 2)}", 
            True, (0, 255, 0)
        )
        screen.blit(other_target_text, (control_panel_x + 10, y_pos))
        
        # Display end effector position
        y_pos += 35
        ee_text = font.render(
            f"End Effector: ({ee_pos_arm1[0]:.3f}, {ee_pos_arm1[1]:.3f}) [Comp Y: {ee_pos_arm1[1] - tip_length * math.sin(pitch_1):.3f}]", 
            True, (255, 100, 100)
        )
        screen.blit(ee_text, (control_panel_x + 10, y_pos))
        
        # Display current action values (velocities) in logical groups
        y_pos += 35
        
        # Group 1: Base control [0,1]
        if len(action) >= 2:
            base_actions = action[0:2]
            base_action_text = font.render(
                f"Base Velocity [0,1]: {np.round(base_actions, 2)}", 
                True, (255, 255, 255)
            )
            screen.blit(base_action_text, (control_panel_x + 10, y_pos))
        
        # Group 2: Arm [2,3,4,5,6]
        y_pos += 25
        if len(action) >= 7:
            arm_actions = action[2:7]
            arm_action_text = font.render(
                f"Arm Velocity [2,3,4,5,6]: {np.round(arm_actions, 2)}", 
                True, (255, 255, 255)
            )
            screen.blit(arm_action_text, (control_panel_x + 10, y_pos))
        
        # Group 3: Gripper and Head [7,8,9]
        y_pos += 25
        if len(action) >= 10:
            other_actions = action[7:10]
            other_action_text = font.render(
                f"Gripper+Head Velocity [7,8,9]: {np.round(other_actions, 2)}", 
                True, (255, 255, 255)
            )
            screen.blit(other_action_text, (control_panel_x + 10, y_pos))
        
        # Display pitch adjustment
        y_pos += 35
        pitch_text = font.render(
            f"Pitch Adjustment: {pitch_1:.3f} (O/0)", 
            True, (255, 100, 255)
        )
        screen.blit(pitch_text, (control_panel_x + 10, y_pos))
        
        pygame.display.flip()


        
        obs, reward, terminated, truncated, info = env.step(action)
        step_counter += 1
        
        # Force second arm to stay in fixed position after each step
        if robot is not None and step_counter > warmup_steps:
            # Set fixed positions for second arm joints based on xlerobot keyframe
            current_qpos = robot.get_qpos()
            if hasattr(current_qpos, 'clone'):
                new_qpos = current_qpos.clone()
            else:
                new_qpos = current_qpos.copy()
            
            # Force second arm to fixed positions (from xlerobot keyframe rest position)
            # Second arm joints: [4,7,10,12,14] (Rotation_2, Pitch_2, Elbow_2, Wrist_Pitch_2, Wrist_Roll_2)
            if len(new_qpos.shape) > 1:
                new_qpos = new_qpos.squeeze()
            
            if len(new_qpos) >= 17:
                new_qpos[4] = 0.0    # Rotation_2 
                new_qpos[7] = 3.14   # Pitch_2
                new_qpos[10] = 3.14  # Elbow_2
                new_qpos[12] = 0.0   # Wrist_Pitch_2
                new_qpos[14] = 1.57  # Wrist_Roll_2
                new_qpos[16] = 0.0   # Jaw_2 (gripper)
                
                # Set the new joint positions
                robot.set_qpos(new_qpos)
        
        if args.render_mode is not None:
            env.render()
        
        time.sleep(0.01)
        
        if args.render_mode is None or args.render_mode != "human":
            if (terminated | truncated).any():
                break
    
    pygame.quit()
    env.close()

    if record_dir:
        print(f"Saving video to {record_dir}")


if __name__ == "__main__":
    parsed_args = tyro.cli(Args)
    main(parsed_args)
