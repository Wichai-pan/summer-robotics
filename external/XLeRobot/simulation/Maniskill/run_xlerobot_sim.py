#!/usr/bin/env python
"""
Script to run XLeRobot simulation in ManiSkill
"""
import sys
import os

# Add the current directory to path to ensure local modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the XLeRobot agents to register them
from agents.xlerobot import xlerobot

# Now import and run the demo
import gymnasium as gym
import numpy as np
import sapien
from mani_skill.envs.sapien_env import BaseEnv
from mani_skill.utils import gym_utils

def main():
    print("Starting XLeRobot simulation...")
    
    # Environment configuration
    env_kwargs = dict(
        obs_mode="state",
        control_mode="pd_joint_delta_pos",
        render_mode="human",
        robot_uids="xlerobot_single",
        num_envs=1,
        sim_backend="auto",
    )
    
    # Create environment
    try:
        env: BaseEnv = gym.make("PushCube-v1", **env_kwargs)
        print("Environment created successfully!")
        
        # Print environment info
        print(f"Observation space: {env.observation_space}")
        print(f"Action space: {env.action_space}")
        if env.unwrapped.agent is not None:
            print(f"Control mode: {env.unwrapped.e}")
        print(f"Reward mode: {env.unwrapped.reward_mode}")
        
        # Reset environment
        obs, _ = env.reset(seed=2022, options=dict(reconfigure=True))
        
        # Render initial state
        if env_kwargs["render_mode"] is not None:
            viewer = env.render()
            if isinstance(viewer, sapien.utils.Viewer):
                viewer.paused = False
            env.render()
        
        # Run simulation loop
        print("\nSimulation is running. Close the viewer window to exit.")
        print("\nKeyboard Controls:")
        print("- W/S: Base Forward/Back")
        print("- A/D: Base Rotation")
        print("- Arrow keys: Arm control")
        print("- Space: Pause/Resume")
        
        action = env.action_space.sample() if env.action_space is not None else None
        action = np.zeros_like(action)
        
        while True:
            obs, reward, terminated, truncated, info = env.step(action)

            if env_kwargs["render_mode"] is not None:
                env.render()
            
            if (terminated | truncated).any():
                obs, _ = env.reset()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'env' in locals():
            env.close()

if __name__ == "__main__":
    main()