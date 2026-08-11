#!/usr/bin/env python3
"""Run a short, supervised ACT action chunk on the physical white arm.

This is the deployment gate after the single-action smoke test.  One live
Gemini+wrist observation produces an ACT chunk; only the first ``--steps``
actions are executed at the dataset control rate.  Every action is clamped to
the training support and re-limited against fresh encoder feedback.  The wrist
uses velocity mode and is stopped before torque is released.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import torch


POSITION_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "gripper",
)
WRIST = "wrist_roll"
OBSERVATION_KEYS = (
    "observation.state",
    "observation.images.gemini_rgb",
    "observation.images.white_wrist_rgb",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", default="forestbridge/fixed-pick-place-v1")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--white-port")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--folded-pose-json",
        type=Path,
        default=Path("/data/act/config/white_folded_pose_v1.json"),
    )
    parser.add_argument("--folded-tolerance-deg", type=float, default=8.0)
    parser.add_argument("--folded-gripper-tolerance", type=float, default=10.0)
    parser.add_argument("--white-wrist-device", default="/dev/wrist-2-4-1")
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=480)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--max-camera-age-s", type=float, default=0.5)
    parser.add_argument("--max-state-range-tolerance", type=float, default=1.0)
    parser.add_argument("--max-arm-step-deg", type=float, default=1.0)
    parser.add_argument("--max-gripper-step", type=float, default=2.0)
    parser.add_argument("--max-wrist-speed-deg-s", type=float, default=1.0)
    parser.add_argument("--max-total-arm-travel-deg", type=float, default=12.0)
    parser.add_argument("--max-total-gripper-travel", type=float, default=24.0)
    parser.add_argument("--tracking-error-deg", type=float, default=4.0)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def total_travel_violations(
    start: dict[str, float],
    current: dict[str, float],
    arm_limit: float,
    gripper_limit: float,
) -> dict[str, float]:
    violations = {}
    for joint in POSITION_JOINTS:
        delta = current[joint] - start[joint]
        limit = gripper_limit if joint == "gripper" else arm_limit
        if abs(delta) > limit:
            violations[joint] = delta
    return violations


def action_dict(names: list[str], values: list[float]) -> dict[str, float]:
    if len(names) != len(values):
        raise ValueError("action names and values must have equal length")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("policy produced a non-finite action")
    return dict(zip(names, values, strict=True))


def main() -> int:
    args = parse_args()
    positive = (
        args.fps,
        args.folded_tolerance_deg,
        args.folded_gripper_tolerance,
        args.max_camera_age_s,
        args.max_state_range_tolerance,
        args.max_arm_step_deg,
        args.max_gripper_step,
        args.max_wrist_speed_deg_s,
        args.max_total_arm_travel_deg,
        args.max_total_gripper_travel,
        args.tracking_error_deg,
    )
    if args.steps <= 0 or any(
        not math.isfinite(value) or value <= 0 for value in positive
    ):
        raise SystemExit("steps, rates and safety limits must be positive")
    if not args.checkpoint.is_dir() or not args.dataset_root.is_dir():
        raise SystemExit("checkpoint and dataset root must exist")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but is unavailable")
    if args.execute and not sys.stdin.isatty():
        raise SystemExit("interactive TTY required for --execute")

    from act_checkpoint_dry_run import (
        clamp_live_state_to_training_range,
        guarded_action,
        positions_from_single_raw_sync,
        rgb_to_policy_tensor,
        state_values,
        wait_for_stable_wrist_raw,
    )
    from act_episode_recorder import GeminiRGBSource, OpenCVRGBSource
    from black_leads_white_wrap_safe import (
        DEG_PER_TICK,
        configure_white_torque_free,
        folded_pose_violations,
        load_folded_pose,
        positions,
        raw_wrist,
        seed_position_goals_from_feedback,
        wrapped_tick_delta,
    )
    from portutil import BOARDS, PortResolutionError, resolve_port
    from wrist_roll_velocity_follow import velocity_command_raw

    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.motors.feetech import OperatingMode
    from lerobot.policies.factory import get_policy_class, make_pre_post_processors
    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    dataset = LeRobotDataset(
        repo_id=args.repo_id,
        root=args.dataset_root,
        video_backend="pyav",
        download_videos=False,
    )
    if int(dataset.fps) != int(args.fps):
        raise SystemExit(f"dataset is {dataset.fps} FPS, requested rollout is {args.fps} FPS")
    config = PreTrainedConfig.from_pretrained(args.checkpoint)
    if args.steps > int(config.n_action_steps):
        raise SystemExit(
            f"--steps {args.steps} exceeds checkpoint n_action_steps={config.n_action_steps}"
        )
    device = torch.device(args.device)
    config.device = str(device)
    if hasattr(config, "pretrained_backbone_weights"):
        config.pretrained_backbone_weights = None
    policy = get_policy_class(config.type).from_pretrained(
        args.checkpoint, config=config
    ).to(device)
    policy.eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=config,
        pretrained_path=str(args.checkpoint),
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )

    action_names = list(dataset.meta.features["action"]["names"])
    state_names = list(dataset.meta.features["observation.state"]["names"])
    action_stats = dataset.meta.stats["action"]
    action_minimum = [float(value) for value in action_stats["min"]]
    action_maximum = [float(value) for value in action_stats["max"]]
    state_stats = dataset.meta.stats["observation.state"]
    state_minimum = [float(value) for value in state_stats["min"]]
    state_maximum = [float(value) for value in state_stats["max"]]

    try:
        port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    robot = SO100Follower(
        SO100FollowerConfig(
            port=port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )
    gemini = GeminiRGBSource(args.camera_width, args.camera_height, args.camera_fps)
    wrist_camera = OpenCVRGBSource(
        args.white_wrist_device,
        args.camera_width,
        args.camera_height,
        args.camera_fps,
    )
    connected = False
    cameras_started = False
    torque_enabled = False
    wrist_velocity_mode = False
    try:
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.white_id}")
        folded_reference, folded_wrist_raw = load_folded_pose(args.folded_pose_json)
        position_state = positions(robot.get_observation())
        position_wrist_raw = raw_wrist(robot.bus)
        violations = folded_pose_violations(
            position_state,
            folded_reference,
            args.folded_tolerance_deg,
            args.folded_gripper_tolerance,
            current_wrist_raw=position_wrist_raw,
            reference_wrist_raw=folded_wrist_raw,
        )
        if violations:
            detail = ", ".join(
                f"{joint}={error:+.1f}" for joint, error in violations.items()
            )
            raise RuntimeError(f"white arm is not at folded start pose: {detail}")

        configure_white_torque_free(robot)
        wrist_velocity_mode = True
        wait_for_stable_wrist_raw(robot.bus)
        seed_position_goals_from_feedback(robot)
        start_state, start_raw = positions_from_single_raw_sync(robot)
        start_wrist_raw = start_raw[WRIST] % 4096

        gemini.start()
        wrist_camera.start()
        cameras_started = True

        def observation_from_live(current_state: dict[str, float]) -> dict[str, torch.Tensor]:
            values = state_values(current_state, state_names)
            model_values, _ = clamp_live_state_to_training_range(
                values,
                state_minimum,
                state_maximum,
                args.max_state_range_tolerance,
            )
            gemini_frame = gemini.latest(args.max_camera_age_s)
            wrist_frame = wrist_camera.latest(args.max_camera_age_s)
            return {
                "observation.state": torch.tensor(
                    model_values, dtype=torch.float32
                ).unsqueeze(0),
                "observation.images.gemini_rgb": rgb_to_policy_tensor(
                    gemini_frame.rgb
                ).unsqueeze(0),
                "observation.images.white_wrist_rgb": rgb_to_policy_tensor(
                    wrist_frame.rgb
                ).unsqueeze(0),
            }

        policy.reset()
        initial_observation = observation_from_live(start_state)
        def next_policy_action(observation: dict[str, torch.Tensor]) -> list[float]:
            autocast_context = (
                torch.autocast(device_type="cuda")
                if device.type == "cuda" and config.use_amp
                else nullcontext()
            )
            with torch.inference_mode(), autocast_context:
                processed = preprocessor(observation)
                predicted = policy.select_action(processed)
                predicted = postprocessor(predicted)
            return [float(value) for value in predicted.squeeze(0).cpu().tolist()]

        first_predicted = next_policy_action(initial_observation)
        first_guarded, first_reasons = guarded_action(
            first_predicted,
            action_names,
            action_minimum,
            action_maximum,
            state_values(start_state, state_names),
            state_names,
            args.max_arm_step_deg,
            args.max_gripper_step,
            args.max_wrist_speed_deg_s,
        )
        print("ACT 短 rollout 已准备；目前仍为松扭矩。")
        print(
            json.dumps(
                {
                    "steps": args.steps,
                    "duration_s": args.steps / args.fps,
                    "chunk_size": int(config.chunk_size),
                    "n_action_steps": int(config.n_action_steps),
                    "start_state": start_state,
                    "first_predicted": action_dict(action_names, first_predicted),
                    "first_guarded": action_dict(action_names, first_guarded),
                    "first_guard_reasons": first_reasons,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        if not args.execute:
            print("DRY RUN：未启用扭矩或发送动作。添加 --execute 才允许短 rollout。")
            return 0
        if input(
            "清空白臂全程运动空间并保持可立即断开12V；输入 ROLLOUT 执行："
        ).strip() != "ROLLOUT":
            print("已取消；没有启用扭矩或发送动作。")
            return 0

        robot.bus.enable_torque(list(POSITION_JOINTS))
        torque_enabled = True
        robot.bus.enable_torque(WRIST)
        period = 1.0 / args.fps
        trace = []
        last_command = {joint: start_state[joint] for joint in POSITION_JOINTS}
        maximum_tracking_error = {joint: 0.0 for joint in POSITION_JOINTS}
        for step_index in range(args.steps):
            loop_started = time.monotonic()
            current_state, current_raw = positions_from_single_raw_sync(robot)
            predicted = (
                first_predicted
                if step_index == 0
                else next_policy_action(observation_from_live(current_state))
            )
            guarded, reasons = guarded_action(
                predicted,
                action_names,
                action_minimum,
                action_maximum,
                state_values(current_state, state_names),
                state_names,
                args.max_arm_step_deg,
                args.max_gripper_step,
                args.max_wrist_speed_deg_s,
            )
            command = action_dict(action_names, guarded)
            position_command = {
                joint: command[f"{joint}.pos"] for joint in POSITION_JOINTS
            }
            wrist_speed = command["wrist_roll.vel_deg_s"]
            wrist_velocity_raw = velocity_command_raw(
                wrist_speed,
                gain=1.0,
                maximum_deg_s=args.max_wrist_speed_deg_s,
                deadband_deg=0.01,
            )
            robot.bus.sync_write("Goal_Position", position_command)
            robot.bus.write(
                "Goal_Velocity", WRIST, wrist_velocity_raw, normalize=False
            )
            last_command = position_command

            violations = total_travel_violations(
                start_state,
                current_state,
                args.max_total_arm_travel_deg,
                args.max_total_gripper_travel,
            )
            if violations:
                detail = ", ".join(
                    f"{joint}={delta:+.1f}" for joint, delta in violations.items()
                )
                raise RuntimeError(f"rollout total travel limit exceeded: {detail}")
            wrist_travel = (
                wrapped_tick_delta(current_raw[WRIST] % 4096, start_wrist_raw)
                * DEG_PER_TICK
            )
            if abs(wrist_travel) > args.max_wrist_speed_deg_s * (
                args.steps / args.fps
            ) + 1.0:
                raise RuntimeError("wrist total travel exceeded rollout safety margin")
            for joint in POSITION_JOINTS:
                error = abs(position_command[joint] - current_state[joint])
                maximum_tracking_error[joint] = max(
                    maximum_tracking_error[joint], error
                )
                if joint != "gripper" and error > args.tracking_error_deg:
                    raise RuntimeError(
                        f"tracking error {error:.1f}° on {joint} exceeds "
                        f"{args.tracking_error_deg:.1f}°"
                    )
            trace.append(
                {
                    "step": step_index,
                    "state": current_state,
                    "command": command,
                    "guard_reasons": reasons,
                }
            )
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        robot.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
        final_state, final_raw = positions_from_single_raw_sync(robot)
        final_violations = total_travel_violations(
            start_state,
            final_state,
            args.max_total_arm_travel_deg,
            args.max_total_gripper_travel,
        )
        if final_violations:
            detail = ", ".join(
                f"{joint}={delta:+.1f}" for joint, delta in final_violations.items()
            )
            raise RuntimeError(f"final rollout travel limit exceeded: {detail}")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "policy_steps_executed": args.steps,
                    "duration_s": args.steps / args.fps,
                    "start_state": start_state,
                    "last_position_command": last_command,
                    "final_state_before_release": final_state,
                    "maximum_tracking_error": maximum_tracking_error,
                    "wrist_travel_deg": wrapped_tick_delta(
                        final_raw[WRIST] % 4096, start_wrist_raw
                    )
                    * DEG_PER_TICK,
                    "trace_first": trace[0],
                    "trace_last": trace[-1],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        if cameras_started:
            gemini.close()
            wrist_camera.close()
        if connected:
            try:
                if wrist_velocity_mode:
                    robot.bus.write(
                        "Goal_Velocity", WRIST, 0, normalize=False, num_retry=3
                    )
                if torque_enabled:
                    robot.bus.disable_torque(num_retry=3)
                robot.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            finally:
                robot.bus.disconnect(disable_torque=False)
            print("白腕已发送零速度；白臂已松开全部扭矩并恢复位置模式。")


if __name__ == "__main__":
    raise SystemExit(main())
