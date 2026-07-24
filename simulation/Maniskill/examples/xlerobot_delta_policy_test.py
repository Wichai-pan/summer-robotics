#!/usr/bin/env python3
"""Run one small delta-action policy in ManiSkill or on the real XLeRobot."""

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass

import numpy as np


ACTION_NAMES = (
    "x.vel",
    "theta.vel",
    "left_arm_shoulder_pan.pos",
    "left_arm_shoulder_lift.pos",
    "left_arm_elbow_flex.pos",
    "left_arm_wrist_flex.pos",
    "left_arm_wrist_roll.pos",
    "right_arm_shoulder_pan.pos",
    "right_arm_shoulder_lift.pos",
    "right_arm_elbow_flex.pos",
    "right_arm_wrist_flex.pos",
    "right_arm_wrist_roll.pos",
    "left_arm_gripper.pos",
    "right_arm_gripper.pos",
    "head_motor_1.pos",
    "head_motor_2.pos",
)
ACTION_INDEX = {name: idx for idx, name in enumerate(ACTION_NAMES)}


@dataclass
class DeltaPolicyConfig:
    joint: str
    amplitude: float
    period_s: float


def delta_policy(t: float, config: DeltaPolicyConfig) -> dict[str, float]:
    """A tiny policy: one selected command varies slowly, everything else is zero."""
    return {
        config.joint: config.amplitude * 10,
        "x.vel": 0.0,
        "theta.vel": 0.0,
    }


def delta_dict_to_sim_action(delta: dict[str, float], action_shape: tuple[int, ...]) -> np.ndarray:
    action = np.zeros(action_shape, dtype=np.float32)
    for name, value in delta.items():
        idx = ACTION_INDEX.get(name)
        if idx is not None and idx < action.size:
            action[idx] = value
    return action


def delta_dict_to_real_action(delta: dict[str, float], observation: dict) -> dict[str, float]:
    """Convert small joint deltas to real absolute position targets.

    Base velocity commands are already velocity commands, so they pass through.
    """
    action: dict[str, float] = {}
    for name, value in delta.items():
        if name.endswith(".vel"):
            action[name] = value
        elif name.endswith(".pos"):
            action[name] = float(observation.get(name, 0.0)) + value
    return action


def run_sim(args: argparse.Namespace) -> None:
    import gymnasium as gym
    import sapien

    maniskill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, maniskill_dir)
    from agents.xlerobot import xlerobot  # noqa: F401

    env = gym.make(
        args.env_id,
        obs_mode="state",
        control_mode=args.control_mode,
        render_mode=args.render_mode,
        robot_uids=args.robot,
        sensor_configs=dict(shader_pack=args.shader),
        human_render_camera_configs=dict(shader_pack=args.shader),
        viewer_camera_configs=dict(shader_pack=args.shader),
        num_envs=1,
        sim_backend="auto",
    )

    try:
        print("Observation space:", env.observation_space)
        print("Action space:", env.action_space)
        env.reset(seed=args.seed, options=dict(reconfigure=True))

        render_enabled = args.render_mode is not None
        if render_enabled:
            try:
                viewer = env.render()
                if isinstance(viewer, sapien.utils.Viewer):
                    viewer.paused = False
            except RuntimeError as exc:
                if not args.ignore_render_errors:
                    raise
                print(f"Render failed once, continuing without viewer: {exc}")
                render_enabled = False

        policy_config = DeltaPolicyConfig(args.joint, args.amplitude, args.period)
        dt = 1.0 / args.hz
        start_t = time.time()
        step = 0

        while time.time() - start_t < args.duration:
            t = time.time() - start_t
            delta = delta_policy(t, policy_config)
            action = delta_dict_to_sim_action(delta, env.action_space.shape)
            _obs, _reward, terminated, truncated, _info = env.step(action)

            if step % args.render_every == 0 and render_enabled:
                try:
                    env.render()
                except RuntimeError as exc:
                    if not args.ignore_render_errors:
                        raise
                    print(f"Render failed, disabling viewer and continuing: {exc}")
                    render_enabled = False
            if (terminated | truncated).any():
                env.reset()
            if step % max(int(args.hz), 1) == 0:
                print(f"t={t:6.2f}s {args.joint} delta={delta.get(args.joint, 0.0): .4f}")

            step += 1
            time.sleep(dt)
    finally:
        env.close()


def run_real(args: argparse.Namespace) -> None:
    repo_software_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "software"))
    sys.path.insert(0, os.path.join(repo_software_dir, "src"))

    from lerobot.robots.xlerobot import XLerobot, XLerobotConfig

    robot_config = XLerobotConfig(
        port1=args.port1,
        port2=args.port2,
        max_relative_target=args.max_relative_target,
        use_degrees=args.use_degrees,
    )
    robot = XLerobot(robot_config)
    policy_config = DeltaPolicyConfig(args.joint, args.amplitude, args.period)
    dt = 1.0 / args.hz

    try:
        robot.connect()
        start_t = time.time()
        while time.time() - start_t < args.duration:
            t = time.time() - start_t
            obs = robot.get_observation()
            delta = delta_policy(t, policy_config)
            action = delta_dict_to_real_action(delta, obs)
            robot.send_action(action)
            time.sleep(dt)
    finally:
        try:
            robot.stop_base()
        except Exception:
            pass
        robot.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("sim", "real"), default="sim")
    parser.add_argument("--joint", default="head_motor_1.pos", choices=ACTION_NAMES)
    parser.add_argument("--amplitude", type=float, default=0.02)
    parser.add_argument("--period", type=float, default=6.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--hz", type=float, default=30.0)

    parser.add_argument("--env-id", default="ReplicaCAD_SceneManipulation-v1")
    parser.add_argument("--robot", default="xlerobot")
    parser.add_argument("--control-mode", default="pd_joint_delta_pos_dual_arm")
    parser.add_argument("--render-mode", default="human")
    parser.add_argument("--render-every", type=int, default=2)
    parser.add_argument("--ignore-render-errors", action="store_true")
    parser.add_argument("--shader", default="default")
    parser.add_argument("--seed", type=int, default=2022)

    parser.add_argument("--port1", default="/dev/ttyACM0")
    parser.add_argument("--port2", default="/dev/ttyACM1")
    parser.add_argument("--max-relative-target", type=float, default=3.0)
    parser.add_argument("--use-degrees", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "sim":
        run_sim(args)
    else:
        run_real(args)


if __name__ == "__main__":
    main()
