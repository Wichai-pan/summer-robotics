#!/usr/bin/env python3
"""Scripted arm-only push test for XLeRobot in ManiSkill PushCube-v1.

This is meant as a tunable visual smoke test, not a solved policy. It keeps the
mobile base still, moves arm1 toward a configurable pushing posture, then slowly
drives one arm joint to push the cube on the table.
"""

import argparse
import os
import sys
import time
from typing import Any

import numpy as np


ARM1_ACTION_SLICE = slice(2, 7)
ARM2_ACTION_SLICE = slice(7, 12)
GRIPPER1_INDEX = 12
GRIPPER2_INDEX = 13
HEAD_ACTION_SLICE = slice(14, 16)

# Default tabletop layout for XLeRobot. PushCube-v1's original table surface is
# z=0, which is too low for this full mobile robot model.
DEFAULT_SCENE_X = 0.0
DEFAULT_SCENE_Y = 0.0
DEFAULT_TABLE_Z = 0.73
DEFAULT_TABLE_SIZE_X = 0.45
DEFAULT_TABLE_SIZE_Y = 0.32
DEFAULT_TABLE_THICKNESS = 0.05
DEFAULT_CUBE_XYZ = "0.05,0.0,0.75"
DEFAULT_GOAL_DX = 0.18
DEFAULT_GOAL_DY = 0.0


def to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def first_pos_from_pose(actor: Any) -> np.ndarray | None:
    if actor is None:
        return None
    pose = getattr(actor, "pose", None)
    if pose is None:
        return None
    pos = to_numpy(pose.p)
    if pos.ndim > 1:
        pos = pos[0]
    return pos


def first_xyz(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    arr = to_numpy(value)
    if arr.ndim > 1:
        arr = arr[0]
    return arr[:3]


def pose_xyz(actor: Any) -> np.ndarray | None:
    return first_pos_from_pose(actor)


def set_actor_xyz(actor: Any, xyz: np.ndarray, sapien_module: Any) -> None:
    if actor is None:
        return
    pose = getattr(actor, "pose", None)
    if pose is None:
        return
    q = to_numpy(pose.q)
    if q.ndim > 1:
        q = q[0]
    actor.set_pose(
        sapien_module.Pose(
            p=np.asarray(xyz, dtype=np.float32),
            q=np.asarray(q, dtype=np.float32),
        )
    )


def move_actor_by(actor: Any, delta_xyz: np.ndarray, sapien_module: Any) -> None:
    xyz = pose_xyz(actor)
    if xyz is None:
        return
    set_actor_xyz(actor, xyz + delta_xyz, sapien_module)


def place_push_scene(env: Any, args: argparse.Namespace, sapien_module: Any) -> None:
    table_scene = getattr(env.unwrapped, "table_scene", None)
    original_table = getattr(table_scene, "table", None)
    if original_table is not None:
        set_actor_xyz(original_table, np.asarray([4.0, 0.0, -2.0], dtype=np.float32), sapien_module)

    scene = getattr(env.unwrapped, "scene", None)
    if scene is not None:
        builder = scene.create_actor_builder()
        table_center = np.asarray(
            [
                args.scene_x,
                args.scene_y,
                args.table_z - args.table_thickness / 2.0,
            ],
            dtype=np.float32,
        )
        builder.add_box_collision(
            pose=sapien_module.Pose(),
            half_size=[
                args.table_size_x / 2.0,
                args.table_size_y / 2.0,
                args.table_thickness / 2.0,
            ],
        )
        builder.add_box_visual(
            pose=sapien_module.Pose(),
            half_size=[
                args.table_size_x / 2.0,
                args.table_size_y / 2.0,
                args.table_thickness / 2.0,
            ],
            material=[0.45, 0.43, 0.38, 1.0],
        )
        builder.initial_pose = sapien_module.Pose(p=table_center)
        env.unwrapped.xlerobot_push_table = builder.build_kinematic(name="xlerobot-push-table")

    cube = getattr(env.unwrapped, "obj", None)
    goal = getattr(env.unwrapped, "goal_region", None)
    cube_xyz = np.asarray(args.cube_xyz, dtype=np.float32)
    goal_xyz = cube_xyz + np.asarray([args.goal_dx, args.goal_dy, 0.0], dtype=np.float32)
    goal_xyz[2] = args.table_z + 1e-3
    set_actor_xyz(cube, cube_xyz, sapien_module)
    set_actor_xyz(goal, goal_xyz, sapien_module)


def get_agent_robot(env: Any) -> Any | None:
    agent = getattr(env.unwrapped, "agent", None)
    if agent is None:
        return None
    return getattr(agent, "robot", None)


def get_mapped_qpos(env: Any, action_shape: tuple[int, ...]) -> np.ndarray:
    robot = get_agent_robot(env)
    mapped = np.zeros(action_shape, dtype=np.float32)
    if robot is None:
        return mapped

    qpos = to_numpy(robot.get_qpos())
    if qpos.ndim > 1:
        qpos = qpos[0]

    # Mapping used by XLeRobot's ManiSkill demo_ctrl_action.py.
    if qpos.size >= 17 and mapped.size >= 16:
        mapped[0] = qpos[0]
        mapped[1] = qpos[2]
        mapped[2:7] = qpos[[3, 6, 9, 11, 13]]
        mapped[7:12] = qpos[[4, 7, 10, 12, 14]]
        mapped[12] = qpos[15]
        mapped[13] = qpos[16]
        mapped[14] = qpos[5]
        mapped[15] = qpos[8]
    return mapped


def parse_target(values: str) -> np.ndarray:
    parts = [float(v.strip()) for v in values.split(",") if v.strip()]
    if len(parts) != 5:
        raise argparse.ArgumentTypeError("Expected five comma-separated joint values")
    return np.asarray(parts, dtype=np.float32)


def parse_xyz(values: str) -> np.ndarray:
    parts = [float(v.strip()) for v in values.split(",") if v.strip()]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Expected three comma-separated xyz values")
    return np.asarray(parts, dtype=np.float32)


def joint_target_action(
    current: np.ndarray,
    target: np.ndarray,
    action_shape: tuple[int, ...],
    args: argparse.Namespace,
) -> np.ndarray:
    action = np.zeros(action_shape, dtype=np.float32)
    error = target - current[ARM1_ACTION_SLICE]
    action[ARM1_ACTION_SLICE] = np.clip(args.kp * error, -args.delta_limit, args.delta_limit)
    if action.size > GRIPPER1_INDEX:
        action[GRIPPER1_INDEX] = args.gripper_open
    if action.size > GRIPPER2_INDEX:
        action[GRIPPER2_INDEX] = args.gripper_open
    return action


def arm_push_action(
    current: np.ndarray,
    base_target: np.ndarray,
    step_in_phase: int,
    action_shape: tuple[int, ...],
    args: argparse.Namespace,
) -> np.ndarray:
    push_target = base_target.copy()
    push_target[args.push_joint] += args.push_distance * min(step_in_phase / max(args.push_steps, 1), 1.0)
    return joint_target_action(current, push_target, action_shape, args)


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
    parser.add_argument("--reach-steps", type=int, default=140)
    parser.add_argument("--push-steps", type=int, default=120)
    parser.add_argument("--hold-steps", type=int, default=40)
    parser.add_argument("--arm1-target", type=parse_target, default=parse_target("0.0,2.35,2.65,-0.45,1.57"))
    parser.add_argument("--push-joint", type=int, default=0, choices=range(5))
    parser.add_argument("--push-distance", type=float, default=0.35)
    parser.add_argument("--kp", type=float, default=0.65)
    parser.add_argument("--delta-limit", type=float, default=0.06)
    parser.add_argument("--gripper-open", type=float, default=2.5)
    parser.add_argument("--scene-x", type=float, default=DEFAULT_SCENE_X)
    parser.add_argument("--scene-y", type=float, default=DEFAULT_SCENE_Y)
    parser.add_argument("--table-z", type=float, default=DEFAULT_TABLE_Z)
    parser.add_argument("--table-size-x", type=float, default=DEFAULT_TABLE_SIZE_X)
    parser.add_argument("--table-size-y", type=float, default=DEFAULT_TABLE_SIZE_Y)
    parser.add_argument("--table-thickness", type=float, default=DEFAULT_TABLE_THICKNESS)
    parser.add_argument("--cube-xyz", type=parse_xyz, default=parse_xyz(DEFAULT_CUBE_XYZ))
    parser.add_argument("--goal-dx", type=float, default=DEFAULT_GOAL_DX)
    parser.add_argument("--goal-dy", type=float, default=DEFAULT_GOAL_DY)
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
        place_push_scene(env, args, sapien)

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
        cube = getattr(env.unwrapped, "obj", None)
        goal = getattr(env.unwrapped, "goal_region", None)
        agent = getattr(env.unwrapped, "agent", None)

        start_cube = first_pos_from_pose(cube)
        goal_pos = first_pos_from_pose(goal)
        print(f"Start cube xyz: {np.round(start_cube, 3) if start_cube is not None else 'unknown'}")
        print(f"Goal xyz: {np.round(goal_pos, 3) if goal_pos is not None else 'unknown'}")
        print(f"Arm1 target: {np.round(args.arm1_target, 3)}")
        print(f"Push joint: arm1[{args.push_joint}], push distance: {args.push_distance}")

        total_steps = args.steps
        for step in range(total_steps):
            current = get_mapped_qpos(env, env.action_space.shape)
            action = np.zeros(env.action_space.shape, dtype=np.float32)

            if step < args.settle_steps:
                phase = "settle"
            elif step < args.settle_steps + args.reach_steps:
                phase = "reach"
                action = joint_target_action(current, args.arm1_target, env.action_space.shape, args)
            elif step < args.settle_steps + args.reach_steps + args.push_steps:
                phase = "push"
                push_step = step - args.settle_steps - args.reach_steps
                action = arm_push_action(current, args.arm1_target, push_step, env.action_space.shape, args)
            else:
                phase = "hold"
                final_target = args.arm1_target.copy()
                final_target[args.push_joint] += args.push_distance
                action = joint_target_action(current, final_target, env.action_space.shape, args)

            _obs, reward, terminated, truncated, info = env.step(action)

            if step % args.render_every == 0:
                render_enabled = maybe_render(env, render_enabled, args)

            if step % 20 == 0:
                cube_pos = first_pos_from_pose(cube)
                tcp_pos = first_xyz(getattr(agent, "tcp_pos", None)) if agent is not None else None
                success = info.get("success", None) if isinstance(info, dict) else None
                print(
                    f"step={step:03d} phase={phase:<6} arm1={np.round(current[ARM1_ACTION_SLICE], 2)} "
                    f"action_arm1={np.round(action[ARM1_ACTION_SLICE], 3)} "
                    f"tcp={np.round(tcp_pos, 3) if tcp_pos is not None else 'unknown'} "
                    f"cube={np.round(cube_pos, 3) if cube_pos is not None else 'unknown'} "
                    f"reward={to_numpy(reward).reshape(-1)[0]:.3f} success={success}"
                )

            if (terminated | truncated).any():
                print(f"Episode ended at step {step}; stopping scripted rollout.")
                break

            time.sleep(dt)

        end_cube = first_pos_from_pose(cube)
        if start_cube is not None and end_cube is not None:
            print(f"Cube delta xyz: {np.round(end_cube - start_cube, 3)}")
    finally:
        env.close()


if __name__ == "__main__":
    args = parse_args()
    main()
