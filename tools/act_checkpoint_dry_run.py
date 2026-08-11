#!/usr/bin/env python3
"""Load a trained ACT checkpoint and run bounded deployment smoke tests.

By default this program uses only recorded data. Optional live modes can open
the two RGB cameras and read a torque-free white-arm state, but this tool never
enables torque and never sends a position or velocity motion command.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from contextlib import nullcontext
from pathlib import Path

import torch


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
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument(
        "--frame-indices",
        type=str,
        help="comma-separated frame indices; overrides --frame-index",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--live-cameras",
        action="store_true",
        help="replace recorded images with one live Gemini+wrist pair; never opens motors",
    )
    parser.add_argument("--white-wrist-device", default="/dev/wrist-2-4-1")
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=480)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--max-camera-age-s", type=float, default=0.5)
    parser.add_argument(
        "--live-state",
        action="store_true",
        help="read the torque-free white-arm state using recorder wrist semantics",
    )
    parser.add_argument("--white-port")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--folded-pose-json",
        type=Path,
        default=Path("/data/act/config/white_folded_pose_v1.json"),
    )
    parser.add_argument("--folded-tolerance-deg", type=float, default=8.0)
    parser.add_argument("--folded-gripper-tolerance", type=float, default=10.0)
    parser.add_argument(
        "--preview-guarded-action",
        action="store_true",
        help="print a range/rate-limited action from live state; still sends nothing",
    )
    parser.add_argument("--max-arm-step-deg", type=float, default=1.0)
    parser.add_argument("--max-gripper-step", type=float, default=2.0)
    parser.add_argument("--max-wrist-speed-deg-s", type=float, default=1.0)
    parser.add_argument("--max-state-range-tolerance", type=float, default=1.0)
    parser.add_argument(
        "--plan-output",
        type=Path,
        help=(
            "atomically save the one guarded live action for a separate supervised "
            "executor; requires --preview-guarded-action"
        ),
    )
    return parser.parse_args()


def scalar(value: object) -> int:
    if isinstance(value, torch.Tensor):
        return int(value.item())
    return int(value)


def bounds_status(
    values: list[float], minimum: list[float], maximum: list[float]
) -> list[bool]:
    if not (len(values) == len(minimum) == len(maximum)):
        raise ValueError("values and bounds must have the same length")
    return [lo <= value <= hi for value, lo, hi in zip(values, minimum, maximum)]


def parse_frame_indices(value: str | None, fallback: int) -> list[int]:
    if value is None:
        return [fallback]
    try:
        indices = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("--frame-indices must be comma-separated integers") from exc
    if not indices:
        raise ValueError("--frame-indices must contain at least one integer")
    return indices


def rgb_to_policy_tensor(rgb: object) -> torch.Tensor:
    """Convert an RGB uint8 HWC array into a normalized CHW torch tensor."""
    tensor = torch.as_tensor(rgb)
    if tensor.ndim != 3 or tensor.shape[2] != 3 or tensor.dtype != torch.uint8:
        raise ValueError(f"expected RGB uint8 HWC image, got {tensor.shape}/{tensor.dtype}")
    return tensor.permute(2, 0, 1).contiguous().float().div_(255.0)


def state_values(state: dict[str, float], names: list[str]) -> list[float]:
    """Order joint values according to the checkpoint's state feature names."""
    values = []
    for name in names:
        joint = name[:-4] if name.endswith(".pos") else name
        if joint not in state:
            raise ValueError(f"live state is missing joint {joint!r}")
        values.append(float(state[joint]))
    return values


def guarded_action(
    predicted: list[float],
    action_names: list[str],
    action_minimum: list[float],
    action_maximum: list[float],
    live_state: list[float],
    state_names: list[str],
    max_arm_step_deg: float,
    max_gripper_step: float,
    max_wrist_speed_deg_s: float,
) -> tuple[list[float], dict[str, list[str]]]:
    """Clamp policy output to training support and one bounded control step."""
    if not (
        len(predicted)
        == len(action_names)
        == len(action_minimum)
        == len(action_maximum)
    ):
        raise ValueError("action vectors and action names must have equal length")
    if len(state_names) != len(live_state):
        raise ValueError("live state values and names must have equal length")
    state_by_name = dict(zip(state_names, live_state))
    result: list[float] = []
    reasons: dict[str, list[str]] = {}
    for value, name, lower, upper in zip(
        predicted,
        action_names,
        action_minimum,
        action_maximum,
    ):
        guarded = max(lower, min(upper, value))
        changes: list[str] = []
        if guarded != value:
            changes.append("training_range")
        if name == "wrist_roll.vel_deg_s":
            limited = max(
                -max_wrist_speed_deg_s,
                min(max_wrist_speed_deg_s, guarded),
            )
            if limited != guarded:
                changes.append("wrist_speed")
            guarded = limited
        elif name.endswith(".pos"):
            if name not in state_by_name:
                raise ValueError(f"no matching live state for action {name!r}")
            step = max_gripper_step if name == "gripper.pos" else max_arm_step_deg
            current = state_by_name[name]
            limited = max(current - step, min(current + step, guarded))
            if limited != guarded:
                changes.append("single_step")
            guarded = limited
        result.append(guarded)
        if changes:
            reasons[name] = changes
    return result, reasons


def clamp_live_state_to_training_range(
    values: list[float],
    minimum: list[float],
    maximum: list[float],
    tolerance: float,
    names: list[str] | None = None,
) -> tuple[list[float], list[float]]:
    """Allow tiny encoder jitter outside the corpus, but reject a wrong branch."""
    if not (len(values) == len(minimum) == len(maximum)):
        raise ValueError("state vectors must have equal length")
    clamped = []
    outside = []
    labels = names if names is not None else [f"state[{i}]" for i in range(len(values))]
    if len(labels) != len(values):
        raise ValueError("state names and values must have equal length")
    for value, lower, upper, label in zip(
        values, minimum, maximum, labels, strict=True
    ):
        distance = max(lower - value, value - upper, 0.0)
        if distance > tolerance:
            raise ValueError(
                f"{label} live value {value:.3f} is {distance:.3f} outside "
                f"training range [{lower:.3f}, {upper:.3f}], exceeding "
                f"tolerance {tolerance:.3f}"
            )
        outside.append(distance)
        clamped.append(max(lower, min(upper, value)))
    return clamped, outside


def wait_for_stable_wrist_raw(bus: object, timeout_s: float = 1.5) -> int:
    """Wait until the velocity-mode position representation has settled."""
    from black_leads_white_wrap_safe import raw_wrist

    deadline = time.monotonic() + timeout_s
    recent: list[int] = []
    time.sleep(0.1)
    while time.monotonic() < deadline:
        recent.append(raw_wrist(bus))
        recent = recent[-4:]
        if len(recent) == 4 and max(recent) - min(recent) <= 2:
            return int(round(sum(recent) / len(recent)))
        time.sleep(0.05)
    raise RuntimeError(f"wrist raw position did not stabilize after mode switch: {recent}")


def positions_from_single_raw_sync(robot: object) -> tuple[dict[str, float], dict[str, int]]:
    """Normalize one raw sync-read so wrist raw and angle cannot cross modes."""
    raw_by_name = robot.bus.sync_read("Present_Position", normalize=False)
    raw_by_id = {
        robot.bus.motors[name].id: int(value) for name, value in raw_by_name.items()
    }
    # Use the pinned LeRobot bus calibration on this exact raw sample. Calling
    # get_observation() would perform a second read that can straddle a mode switch.
    normalized_by_id = robot.bus._normalize(raw_by_id)
    normalized = {
        name: float(normalized_by_id[robot.bus.motors[name].id])
        for name in raw_by_name
    }
    return normalized, {name: int(value) for name, value in raw_by_name.items()}


def read_torque_free_white_state(
    args: argparse.Namespace, state_names: list[str]
) -> tuple[list[float], dict[str, object]]:
    """Read the same wrist-state branch used at ACT recording start.

    Register writes are limited to disabling torque, selecting the recorder's
    operating modes and forcing wrist goal velocity to zero.  The wrist is
    restored to position mode before disconnecting.
    """
    from black_leads_white_wrap_safe import (
        WRIST,
        configure_white_torque_free,
        folded_pose_violations,
        load_folded_pose,
        positions,
        raw_wrist,
        wrapped_tick_delta,
    )
    from portutil import BOARDS, PortResolutionError, resolve_port

    try:
        port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise RuntimeError(str(exc)) from exc

    from lerobot.motors.feetech import OperatingMode
    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    if not args.folded_pose_json.is_file():
        raise RuntimeError(f"folded-pose reference not found: {args.folded_pose_json}")
    robot = SO100Follower(
        SO100FollowerConfig(
            port=port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )
    connected = False
    wrist_velocity_mode = False
    try:
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.white_id}")

        folded_reference, folded_wrist_raw = load_folded_pose(args.folded_pose_json)
        position_mode_state = positions(robot.get_observation())
        position_mode_wrist_raw = raw_wrist(robot.bus)
        violations = folded_pose_violations(
            position_mode_state,
            folded_reference,
            args.folded_tolerance_deg,
            args.folded_gripper_tolerance,
            current_wrist_raw=position_mode_wrist_raw,
            reference_wrist_raw=folded_wrist_raw,
        )
        if violations:
            detail = ", ".join(
                f"{joint}={error:+.1f}" for joint, error in violations.items()
            )
            raise RuntimeError(
                "white arm is not at the saved folded pose; "
                f"torque remains disabled ({detail})"
            )

        configure_white_torque_free(robot)
        wrist_velocity_mode = True
        stable_wrist_raw = wait_for_stable_wrist_raw(robot.bus)
        recorder_branch_state, recorder_raw_positions = positions_from_single_raw_sync(robot)
        recorder_branch_wrist_raw = recorder_raw_positions[WRIST] % 4096
        if abs(wrapped_tick_delta(recorder_branch_wrist_raw, stable_wrist_raw)) > 3:
            raise RuntimeError(
                "wrist raw changed between stabilization and synchronized state read: "
                f"{stable_wrist_raw} -> {recorder_branch_wrist_raw}"
            )
        return state_values(recorder_branch_state, state_names), {
            "port": port,
            "robot_id": args.white_id,
            "torque_enabled": False,
            "motion_command_sent": False,
            "position_mode_wrist_raw": position_mode_wrist_raw,
            "recorder_branch_wrist_raw": recorder_branch_wrist_raw,
            "stable_wrist_raw": stable_wrist_raw,
            "position_mode_state": position_mode_state,
            "recorder_branch_state": recorder_branch_state,
        }
    finally:
        if connected:
            try:
                robot.bus.disable_torque(num_retry=3)
                if wrist_velocity_mode:
                    robot.bus.write(
                        "Goal_Velocity", WRIST, 0, normalize=False, num_retry=3
                    )
                robot.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            finally:
                robot.bus.disconnect(disable_torque=False)


def main() -> int:
    args = parse_args()
    if not args.checkpoint.is_dir():
        raise SystemExit(f"checkpoint directory does not exist: {args.checkpoint}")
    if not args.dataset_root.is_dir():
        raise SystemExit(f"dataset directory does not exist: {args.dataset_root}")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but torch.cuda.is_available() is false")

    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import get_policy_class, make_pre_post_processors

    device = torch.device(args.device)
    dataset = LeRobotDataset(
        repo_id=args.repo_id,
        root=args.dataset_root,
        video_backend="pyav",
        download_videos=False,
    )
    try:
        frame_indices = parse_frame_indices(args.frame_indices, args.frame_index)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    invalid = [index for index in frame_indices if not 0 <= index < dataset.num_frames]
    if invalid:
        raise SystemExit(
            f"frame indices {invalid} outside [0, {dataset.num_frames - 1}]"
        )
    if args.live_cameras and len(frame_indices) != 1:
        raise SystemExit("--live-cameras requires exactly one state frame index")
    if args.live_state and len(frame_indices) != 1:
        raise SystemExit("--live-state requires exactly one reference frame index")
    if args.live_state and not args.live_cameras:
        raise SystemExit("--live-state must be paired with --live-cameras")
    if args.preview_guarded_action and not args.live_state:
        raise SystemExit("--preview-guarded-action requires --live-state")
    if args.plan_output is not None and not args.preview_guarded_action:
        raise SystemExit("--plan-output requires --preview-guarded-action")
    if min(
        args.max_arm_step_deg,
        args.max_gripper_step,
        args.max_wrist_speed_deg_s,
        args.max_state_range_tolerance,
    ) <= 0:
        raise SystemExit("guard step and speed limits must be positive")

    config = PreTrainedConfig.from_pretrained(args.checkpoint)
    config.device = str(device)
    # The checkpoint already contains the backbone. Avoid an unrelated network
    # download when an ephemeral deployment container constructs the ACT model.
    if hasattr(config, "pretrained_backbone_weights"):
        config.pretrained_backbone_weights = None
    policy_class = get_policy_class(config.type)
    policy = policy_class.from_pretrained(args.checkpoint, config=config).to(device)
    policy.eval()

    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=config,
        pretrained_path=str(args.checkpoint),
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )

    action_feature = dataset.meta.features["action"]
    action_names = list(action_feature["names"])
    state_feature = dataset.meta.features["observation.state"]
    state_names = list(state_feature["names"])
    stats = dataset.meta.stats["action"]
    minimum = [float(value) for value in stats["min"]]
    maximum = [float(value) for value in stats["max"]]
    samples = []
    absolute_errors: list[list[float]] = []
    range_failures = [0] * len(action_names)
    live_sources = None
    live_samples = None
    live_state_tensor = None
    live_state_diagnostic = None
    state_stats = dataset.meta.stats["observation.state"]
    state_minimum = [float(value) for value in state_stats["min"]]
    state_maximum = [float(value) for value in state_stats["max"]]
    try:
        if args.live_state:
            live_state_values, live_state_diagnostic = read_torque_free_white_state(
                args, state_names
            )
            model_state_values, state_outside_distance = (
                clamp_live_state_to_training_range(
                    live_state_values,
                    state_minimum,
                    state_maximum,
                    args.max_state_range_tolerance,
                    state_names,
                )
            )
            live_state_tensor = torch.tensor(model_state_values, dtype=torch.float32)
            live_state_diagnostic["model_input_state"] = dict(
                zip(state_names, model_state_values, strict=True)
            )
            live_state_diagnostic["outside_training_range_distance"] = dict(
                zip(state_names, state_outside_distance, strict=True)
            )
            live_state_diagnostic["within_training_min_max"] = dict(
                zip(
                    state_names,
                    bounds_status(live_state_values, state_minimum, state_maximum),
                    strict=True,
                )
            )

        if args.live_cameras:
            from act_episode_recorder import GeminiRGBSource, OpenCVRGBSource

            gemini = GeminiRGBSource(args.camera_width, args.camera_height, args.camera_fps)
            wrist = OpenCVRGBSource(
                args.white_wrist_device,
                args.camera_width,
                args.camera_height,
                args.camera_fps,
            )
            live_sources = (gemini, wrist)
            gemini.start()
            wrist.start()
            live_samples = (
                gemini.latest(args.max_camera_age_s),
                wrist.latest(args.max_camera_age_s),
            )

        for frame_index in frame_indices:
            frame = dataset[frame_index]
            missing = [key for key in OBSERVATION_KEYS if key not in frame]
            if missing:
                raise RuntimeError(f"dataset frame is missing policy inputs: {missing}")
            observation = {key: frame[key].unsqueeze(0) for key in OBSERVATION_KEYS}
            if live_state_tensor is not None:
                observation["observation.state"] = live_state_tensor.unsqueeze(0)
            if live_samples is not None:
                observation["observation.images.gemini_rgb"] = rgb_to_policy_tensor(
                    live_samples[0].rgb
                ).unsqueeze(0)
                observation["observation.images.white_wrist_rgb"] = rgb_to_policy_tensor(
                    live_samples[1].rgb
                ).unsqueeze(0)

            # Sampled frames are independent deployment smoke tests. Reset ACT's
            # action-chunk queue so unrelated episodes cannot affect one another.
            policy.reset()
            autocast = (
                torch.autocast(device_type="cuda")
                if device.type == "cuda" and config.use_amp
                else nullcontext()
            )
            with torch.inference_mode(), autocast:
                processed_observation = preprocessor(observation)
                predicted = policy.select_action(processed_observation)
                predicted = postprocessor(predicted)

            predicted_values = [
                float(value) for value in predicted.squeeze(0).cpu().tolist()
            ]
            recorded_values = [float(value) for value in frame["action"].cpu().tolist()]
            if len(predicted_values) != len(recorded_values):
                raise RuntimeError(
                    f"action dimension mismatch: predicted={len(predicted_values)}, "
                    f"recorded={len(recorded_values)}"
                )
            if not all(math.isfinite(value) for value in predicted_values):
                raise RuntimeError(f"policy produced non-finite action: {predicted_values}")
            within_training_range = bounds_status(predicted_values, minimum, maximum)
            guarded_values = None
            guard_reasons = None
            if args.preview_guarded_action:
                assert live_state_values is not None
                guarded_values, guard_reasons = guarded_action(
                    predicted_values,
                    action_names,
                    minimum,
                    maximum,
                    live_state_values,
                    state_names,
                    args.max_arm_step_deg,
                    args.max_gripper_step,
                    args.max_wrist_speed_deg_s,
                )
            errors = [abs(a - b) for a, b in zip(predicted_values, recorded_values)]
            absolute_errors.append(errors)
            for dimension, within in enumerate(within_training_range):
                range_failures[dimension] += int(not within)
            samples.append(
                {
                    "frame_index": frame_index,
                    "episode_index": scalar(frame["episode_index"]),
                    "predicted_action": dict(
                        zip(action_names, predicted_values, strict=True)
                    ),
                    "recorded_action_reference_only": dict(
                        zip(action_names, recorded_values, strict=True)
                    ),
                    "within_training_min_max": dict(
                        zip(action_names, within_training_range, strict=True)
                    ),
                    "guarded_action_no_command": (
                        dict(zip(action_names, guarded_values, strict=True))
                        if guarded_values is not None
                        else None
                    ),
                    "guard_reasons": guard_reasons,
                }
            )
    finally:
        if live_sources is not None:
            live_sources[0].close()
            live_sources[1].close()

    mae = [
        sum(row[i] for row in absolute_errors) / len(samples)
        for i in range(len(action_names))
    ]
    max_error = [
        max(row[i] for row in absolute_errors) for i in range(len(action_names))
    ]

    result = {
        "status": "PASS",
        "hardware_access": {
            "cameras": args.live_cameras,
            "serial_read_only": args.live_state,
            "torque_enabled": False,
            "motion_command_sent": False,
        },
        "input_mode": (
            "live_cameras_live_state"
            if args.live_state
            else "live_cameras_recorded_state"
            if args.live_cameras
            else "recorded"
        ),
        "device": str(device),
        "torch": torch.__version__,
        "policy_type": config.type,
        "checkpoint": str(args.checkpoint),
        "dataset_root": str(args.dataset_root),
        "dataset_episodes": dataset.num_episodes,
        "dataset_frames": dataset.num_frames,
        "sample_count": len(samples),
        "frame_indices": frame_indices,
        "summary": {
            "mae": dict(zip(action_names, mae, strict=True)),
            "max_absolute_error": dict(zip(action_names, max_error, strict=True)),
            "out_of_training_range_count": dict(
                zip(action_names, range_failures, strict=True)
            ),
        },
        "samples": samples,
        "live_state_diagnostic": live_state_diagnostic,
    }
    if args.plan_output is not None:
        guarded = samples[0]["guarded_action_no_command"]
        assert guarded is not None and live_state_diagnostic is not None
        plan = {
            "schema": "forestbridge_act_guarded_step/v1",
            "created_unix_s": time.time(),
            "checkpoint": str(args.checkpoint),
            "dataset_root": str(args.dataset_root),
            "robot_id": args.white_id,
            "live_state": dict(zip(state_names, live_state_values, strict=True)),
            "recorder_branch_wrist_raw": live_state_diagnostic[
                "recorder_branch_wrist_raw"
            ],
            "guarded_action": guarded,
            "guard_reasons": samples[0]["guard_reasons"],
            "limits": {
                "max_arm_step_deg": args.max_arm_step_deg,
                "max_gripper_step": args.max_gripper_step,
                "max_wrist_speed_deg_s": args.max_wrist_speed_deg_s,
            },
            "hardware_access_when_planned": result["hardware_access"],
        }
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.plan_output.with_suffix(args.plan_output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary.replace(args.plan_output)
        result["plan_output"] = str(args.plan_output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
