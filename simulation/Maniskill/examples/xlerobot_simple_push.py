#!/usr/bin/env python3
"""A tiny scripted PushCube smoke test for XLeRobot in ManiSkill.

The policy intentionally uses only the base controls so it is easy to compare
with the real robot later: drive forward for a short window, add a gentle wiggle,
then stop.
"""

import argparse
import os
import sys
import time
from typing import Any

import numpy as np


def to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def first_xy_from_pose(actor: Any) -> np.ndarray | None:
    if actor is None:
        return None
    pose = getattr(actor, "pose", None)
    if pose is None:
        return None
    pos = to_numpy(pose.p)
    if pos.ndim > 1:
        pos = pos[0]
    return pos[:2]


def scripted_push_action(step: int, args: argparse.Namespace, action_shape: tuple[int, ...]) -> np.ndarray:
    action = np.zeros(action_shape, dtype=np.float32)

    if step < args.settle_steps:
        return action

    push_step = step - args.settle_steps
    if push_step < args.push_steps:
        action[0] = args.forward_speed
        if action.size > 1:
            action[1] = args.turn_speed * np.sin(push_step / args.wiggle_period_steps)

    return action


def maybe_render(env: Any, enabled: bool, args: argparse.Namespace) -> bool:
    if not enabled:
        return False
    try:
        env.render()
        return True
    except RuntimeError as exc:
        if args.ignore_render_errors:
            print(f"Render failed; continuing without viewer: {exc}")
            return False
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-id", default="PushCube-v1")
    parser.add_argument("--robot", default="xlerobot")
    parser.add_argument("--control-mode", default="pd_joint_delta_pos_dual_arm")
    parser.add_argument("--obs-mode", default="state")
    parser.add_argument("--render-mode", default="human")
    parser.add_argument("--shader", default="default")
    parser.add_argument("--seed", type=int, default=2022)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--max-episode-steps", type=int, default=500)
    parser.add_argument("--hz", type=float, default=30.0)
    parser.add_argument("--render-every", type=int, default=4)
    parser.add_argument("--ignore-render-errors", action="store_true")

    parser.add_argument("--settle-steps", type=int, default=30)
    parser.add_argument("--push-steps", type=int, default=170)
    parser.add_argument("--forward-speed", type=float, default=0.16)
    parser.add_argument("--turn-speed", type=float, default=0.10)
    parser.add_argument("--wiggle-period-steps", type=float, default=24.0)
    return parser.parse_args()


def main() -> None:
    import gymnasium as gym
    import sapien

    maniskill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, maniskill_dir)
    from agents.xlerobot import xlerobot  # noqa: F401

    render_mode = None if args.render_mode.lower() == "none" else args.render_mode
    env = gym.make(
        args.env_id,
        obs_mode=args.obs_mode,
        control_mode=args.control_mode,
        render_mode=render_mode,
        robot_uids=args.robot,
        sensor_configs=dict(shader_pack=args.shader),
        human_render_camera_configs=dict(shader_pack=args.shader),
        viewer_camera_configs=dict(shader_pack=args.shader),
        num_envs=1,
        sim_backend="auto",
        max_episode_steps=args.max_episode_steps,
    )

    try:
        print("Observation space:", env.observation_space)
        print("Action space:", env.action_space)
        env.reset(seed=args.seed, options=dict(reconfigure=True))

        render_enabled = render_mode is not None
        if render_enabled:
            try:
                viewer = env.render()
                if isinstance(viewer, sapien.utils.Viewer):
                    viewer.paused = False
            except RuntimeError as exc:
                if not args.ignore_render_errors:
                    raise
                print(f"Initial render failed; continuing without viewer: {exc}")
                render_enabled = False

        dt = 1.0 / args.hz
        unwrapped = env.unwrapped
        cube = getattr(unwrapped, "obj", None)
        goal = getattr(unwrapped, "goal_region", None)

        start_cube_xy = first_xy_from_pose(cube)
        goal_xy = first_xy_from_pose(goal)
        print(f"Start cube xy: {np.round(start_cube_xy, 3) if start_cube_xy is not None else 'unknown'}")
        print(f"Goal xy: {np.round(goal_xy, 3) if goal_xy is not None else 'unknown'}")

        for step in range(args.steps):
            action = scripted_push_action(step, args, env.action_space.shape)
            _obs, reward, terminated, truncated, info = env.step(action)

            if step % args.render_every == 0:
                render_enabled = maybe_render(env, render_enabled, args)

            if step % 20 == 0:
                cube_xy = first_xy_from_pose(cube)
                success = info.get("success", None) if isinstance(info, dict) else None
                print(
                    f"step={step:03d} action[:2]={np.round(action[:2], 3)} "
                    f"cube_xy={np.round(cube_xy, 3) if cube_xy is not None else 'unknown'} "
                    f"reward={to_numpy(reward).reshape(-1)[0]:.3f} success={success}"
                )

            if (terminated | truncated).any():
                print(f"Episode ended at step {step}; resetting.")
                env.reset()

            time.sleep(dt)

        end_cube_xy = first_xy_from_pose(cube)
        if start_cube_xy is not None and end_cube_xy is not None:
            print(f"Cube delta xy: {np.round(end_cube_xy - start_cube_xy, 3)}")
    finally:
        env.close()


if __name__ == "__main__":
    args = parse_args()
    main()
