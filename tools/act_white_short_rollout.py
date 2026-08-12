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
        "--start-from-current",
        action="store_true",
        help=(
            "continue a later ACT chunk from the current pose instead of requiring "
            "the saved folded start; live state must still be inside training support"
        ),
    )
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
    parser.add_argument("--max-state-range-tolerance", type=float, default=2.0)
    parser.add_argument("--max-wrist-state-range-tolerance", type=float, default=8.0)
    parser.add_argument("--wrist-support-margin-deg", type=float, default=0.75)
    parser.add_argument("--wrist-support-recovery-deg-s", type=float, default=0.5)
    parser.add_argument("--max-arm-step-deg", type=float, default=1.0)
    parser.add_argument("--max-gripper-step", type=float, default=2.0)
    parser.add_argument("--max-wrist-speed-deg-s", type=float, default=1.0)
    parser.add_argument("--max-total-arm-travel-deg", type=float, default=12.0)
    parser.add_argument(
        "--max-total-elbow-travel-deg",
        type=float,
        help="optional elbow_flex-only travel override; other arm joints keep the arm limit",
    )
    parser.add_argument("--max-total-gripper-travel", type=float, default=24.0)
    parser.add_argument("--tracking-error-deg", type=float, default=4.0)
    parser.add_argument("--tracking-error-gripper", type=float, default=8.0)
    parser.add_argument(
        "--grasp-supervisor",
        action="store_true",
        help=(
            "use gripper position/load/current as a side-channel contact guard; "
            "does not change the ACT observation vector"
        ),
    )
    parser.add_argument("--grasp-contact-min-position", type=float, default=7.0)
    parser.add_argument("--grasp-contact-load-percent", type=float, default=15.0)
    parser.add_argument("--grasp-contact-current-raw", type=int, default=15)
    parser.add_argument("--grasp-contact-confirm-s", type=float, default=0.3)
    parser.add_argument("--grasp-hold-offset", type=float, default=1.25)
    parser.add_argument("--grasp-release-position", type=float, default=20.0)
    parser.add_argument("--grasp-release-confirm-s", type=float, default=0.2)
    parser.add_argument("--grasp-max-hold-s", type=float, default=15.0)
    parser.add_argument("--grasp-max-temperature-c", type=float, default=60.0)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


class GripperContactSupervisor:
    """Latch physical contact and replace further closing with a gentle hold.

    The physical white gripper was verified on 2026-08-12: larger normalized
    positions open the fingers and smaller positions close them.  A contact is
    therefore only considered while the requested position is below feedback.
    """

    def __init__(
        self,
        *,
        minimum_position: float,
        minimum_load_percent: float,
        minimum_current_raw: int,
        confirmation_s: float,
        hold_offset: float,
        release_position: float,
        release_confirmation_s: float,
        maximum_hold_s: float,
    ) -> None:
        self.minimum_position = minimum_position
        self.minimum_load_percent = minimum_load_percent
        self.minimum_current_raw = minimum_current_raw
        self.confirmation_s = confirmation_s
        self.hold_offset = hold_offset
        self.release_position = release_position
        self.release_confirmation_s = release_confirmation_s
        self.maximum_hold_s = maximum_hold_s
        self.candidate_since: float | None = None
        self.latched_at: float | None = None
        self.contact_position: float | None = None
        self.hold_target: float | None = None
        self.release_candidate_since: float | None = None

    @property
    def latched(self) -> bool:
        return self.latched_at is not None

    def update(
        self,
        *,
        now_s: float,
        present_position: float,
        requested_position: float,
        policy_requested_position: float,
        load_raw: int,
        current_raw: int,
    ) -> dict[str, object]:
        load_percent = abs(load_raw) / 10.0
        closing = (
            requested_position < present_position - 0.25
            and policy_requested_position < present_position - 0.25
        )
        contact_signal = (
            closing
            and present_position > self.minimum_position
            and load_percent >= self.minimum_load_percent
            and current_raw >= self.minimum_current_raw
        )
        event: str | None = None

        if not self.latched:
            if contact_signal:
                if self.candidate_since is None:
                    self.candidate_since = now_s
                if now_s - self.candidate_since >= self.confirmation_s:
                    self.latched_at = now_s
                    self.contact_position = present_position
                    self.hold_target = max(0.0, present_position - self.hold_offset)
                    event = "contact_latched"
            else:
                self.candidate_since = None

        guarded_position = requested_position
        guard_reason: str | None = None
        if self.latched:
            assert self.latched_at is not None
            assert self.hold_target is not None
            if now_s - self.latched_at > self.maximum_hold_s:
                raise RuntimeError(
                    f"gripper contact hold exceeded {self.maximum_hold_s:.1f}s"
                )
            if policy_requested_position >= self.release_position:
                if self.release_candidate_since is None:
                    self.release_candidate_since = now_s
                if (
                    now_s - self.release_candidate_since
                    >= self.release_confirmation_s
                ):
                    self.candidate_since = None
                    self.latched_at = None
                    self.contact_position = None
                    self.hold_target = None
                    self.release_candidate_since = None
                    event = "contact_released"
                else:
                    guarded_position = self.hold_target
                    guard_reason = "grasp_contact_hold"
            else:
                self.release_candidate_since = None
                guarded_position = self.hold_target
                guard_reason = "grasp_contact_hold"

        return {
            "requested_position": requested_position,
            "policy_requested_position": policy_requested_position,
            "guarded_position": guarded_position,
            "present_position": present_position,
            "load_raw": load_raw,
            "load_abs_percent": load_percent,
            "current_raw": current_raw,
            "closing": closing,
            "contact_signal": contact_signal,
            "latched": self.latched,
            "contact_position": self.contact_position,
            "hold_target": self.hold_target,
            "release_candidate": self.release_candidate_since is not None,
            "event": event,
            "guard_reason": guard_reason,
        }


def read_gripper_side_channel(bus: object, *, health: bool) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "load_raw": int(
            bus.read("Present_Load", "gripper", normalize=False, num_retry=2)
        ),
        "current_raw": int(
            bus.read("Present_Current", "gripper", normalize=False, num_retry=2)
        ),
        "temperature_c": None,
        "status_raw": None,
    }
    if health:
        result["temperature_c"] = int(
            bus.read("Present_Temperature", "gripper", normalize=False, num_retry=2)
        )
        result["status_raw"] = int(
            bus.read("Status", "gripper", normalize=False, num_retry=2)
        )
    return result


def total_travel_violations(
    start: dict[str, float],
    current: dict[str, float],
    arm_limit: float,
    gripper_limit: float,
    arm_feedback_slack: float = 0.0,
    gripper_feedback_slack: float = 0.0,
    elbow_limit: float | None = None,
) -> dict[str, float]:
    """Find measured travel beyond the command envelope plus tracking slack."""
    violations = {}
    for joint in POSITION_JOINTS:
        delta = current[joint] - start[joint]
        limit = gripper_limit if joint == "gripper" else arm_limit
        if joint == "elbow_flex" and elbow_limit is not None:
            limit = elbow_limit
        limit += (
            gripper_feedback_slack if joint == "gripper" else arm_feedback_slack
        )
        if abs(delta) > limit:
            violations[joint] = delta
    return violations


def action_dict(names: list[str], values: list[float]) -> dict[str, float]:
    if len(names) != len(values):
        raise ValueError("action names and values must have equal length")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("policy produced a non-finite action")
    return dict(zip(names, values, strict=True))


def clamp_position_to_total_envelope(
    command: dict[str, float],
    start: dict[str, float],
    arm_limit: float,
    gripper_limit: float,
    elbow_limit: float | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Ensure even the final transmitted command stays inside total travel."""
    result = {}
    clamped = []
    for joint in POSITION_JOINTS:
        limit = gripper_limit if joint == "gripper" else arm_limit
        if joint == "elbow_flex" and elbow_limit is not None:
            limit = elbow_limit
        lower = start[joint] - limit
        upper = start[joint] + limit
        value = max(lower, min(upper, command[joint]))
        result[joint] = value
        if value != command[joint]:
            clamped.append(joint)
    return result, clamped


def rollout_guarded_action(
    predicted: list[float],
    action_names: list[str],
    action_minimum: list[float],
    action_maximum: list[float],
    previous_command: dict[str, float],
    feedback: dict[str, float],
    arm_step: float,
    gripper_step: float,
    wrist_speed_limit: float,
    arm_tracking_limit: float,
    gripper_tracking_limit: float,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Guard a chunk action using the command-slew semantics used in recording."""
    raw = action_dict(action_names, predicted)
    result: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for name, lower, upper in zip(
        action_names, action_minimum, action_maximum, strict=True
    ):
        requested = raw[name]
        guarded = max(lower, min(upper, requested))
        changes: list[str] = []
        if guarded != requested:
            changes.append("training_range")
        if name == "wrist_roll.vel_deg_s":
            limited = max(-wrist_speed_limit, min(wrist_speed_limit, guarded))
            if limited != guarded:
                changes.append("wrist_speed")
            guarded = limited
        else:
            joint = name.removesuffix(".pos")
            step = gripper_step if joint == "gripper" else arm_step
            tracking = (
                gripper_tracking_limit if joint == "gripper" else arm_tracking_limit
            )
            slewed = previous_command[joint] + max(
                -step, min(step, guarded - previous_command[joint])
            )
            if slewed != guarded:
                changes.append("command_slew")
            feedback_bounded = max(
                feedback[joint] - tracking,
                min(feedback[joint] + tracking, slewed),
            )
            if feedback_bounded != slewed:
                changes.append("tracking_envelope")
            guarded = feedback_bounded
        result[name] = guarded
        if changes:
            reasons[name] = changes
    return result, reasons


def intersect_position_action_with_state_bounds(
    action_names: list[str],
    action_minimum: list[float],
    action_maximum: list[float],
    state_names: list[str],
    state_minimum: list[float],
    state_maximum: list[float],
) -> tuple[list[float], list[float]]:
    """Keep position commands inside both action and observed-state support."""
    state_bounds = {
        name: (lower, upper)
        for name, lower, upper in zip(
            state_names, state_minimum, state_maximum, strict=True
        )
    }
    safe_minimum = []
    safe_maximum = []
    for name, lower, upper in zip(
        action_names, action_minimum, action_maximum, strict=True
    ):
        if name.endswith(".pos") and name in state_bounds:
            state_lower, state_upper = state_bounds[name]
            lower = max(lower, state_lower)
            upper = min(upper, state_upper)
            if lower > upper:
                raise ValueError(f"empty action/state support intersection for {name}")
        safe_minimum.append(lower)
        safe_maximum.append(upper)
    return safe_minimum, safe_maximum


def clamp_rollout_live_state(
    values: list[float],
    minimum: list[float],
    maximum: list[float],
    names: list[str],
    default_tolerance: float,
    wrist_tolerance: float,
) -> tuple[list[float], list[float]]:
    """Clamp model input while giving the cyclic wrist its own recovery window."""
    if not (len(values) == len(minimum) == len(maximum) == len(names)):
        raise ValueError("state vectors and names must have equal length")
    clamped: list[float] = []
    outside: list[float] = []
    for value, lower, upper, name in zip(
        values, minimum, maximum, names, strict=True
    ):
        distance = max(lower - value, value - upper, 0.0)
        tolerance = wrist_tolerance if name == "wrist_roll.pos" else default_tolerance
        if distance > tolerance:
            raise ValueError(
                f"{name} live value {value:.3f} is {distance:.3f} outside "
                f"training range [{lower:.3f}, {upper:.3f}], exceeding "
                f"tolerance {tolerance:.3f}"
            )
        outside.append(distance)
        clamped.append(max(lower, min(upper, value)))
    return clamped, outside


def keep_wrist_velocity_inside_state_support(
    requested_speed: float,
    current_position: float,
    lower: float,
    upper: float,
    margin: float,
    recovery_speed: float,
) -> tuple[float, str | None]:
    """Prevent velocity-mode wrist drift from leaving observed training support."""
    if current_position < lower:
        return max(requested_speed, recovery_speed), "wrist_support_recovery"
    if current_position > upper:
        return min(requested_speed, -recovery_speed), "wrist_support_recovery"
    if current_position <= lower + margin and requested_speed < 0.0:
        return 0.0, "wrist_support_margin"
    if current_position >= upper - margin and requested_speed > 0.0:
        return 0.0, "wrist_support_margin"
    return requested_speed, None


def summarize_policy_chunks(
    trace: list[dict[str, object]],
    n_action_steps: int,
    final_state: dict[str, float],
) -> list[dict[str, object]]:
    """Summarize each ACT replan window without changing rollout behavior."""
    if n_action_steps <= 0:
        raise ValueError("n_action_steps must be positive")
    summaries: list[dict[str, object]] = []
    state_joints = (*POSITION_JOINTS, WRIST)
    for chunk_index, start in enumerate(range(0, len(trace), n_action_steps)):
        stop = min(start + n_action_steps, len(trace))
        records = trace[start:stop]
        start_state = records[0]["state"]
        end_state = trace[stop]["state"] if stop < len(trace) else final_state
        guard_reason_counts: dict[str, int] = {}
        guarded_steps = 0
        for record in records:
            reasons = record["guard_reasons"]
            if reasons:
                guarded_steps += 1
            for action_reasons in reasons.values():
                for reason in action_reasons:
                    guard_reason_counts[reason] = guard_reason_counts.get(reason, 0) + 1
        summaries.append(
            {
                "chunk_index": chunk_index,
                "steps": [start, stop - 1],
                "start_state": start_state,
                "end_state": end_state,
                "state_delta": {
                    joint: end_state[joint] - start_state[joint]
                    for joint in state_joints
                },
                "first_predicted": records[0]["predicted"],
                "first_command": records[0]["command"],
                "last_command": records[-1]["command"],
                "guarded_steps": guarded_steps,
                "guard_reason_counts": guard_reason_counts,
            }
        )
    return summaries


def main() -> int:
    args = parse_args()
    positive = (
        args.fps,
        args.folded_tolerance_deg,
        args.folded_gripper_tolerance,
        args.max_camera_age_s,
        args.max_state_range_tolerance,
        args.max_wrist_state_range_tolerance,
        args.wrist_support_margin_deg,
        args.wrist_support_recovery_deg_s,
        args.max_arm_step_deg,
        args.max_gripper_step,
        args.max_wrist_speed_deg_s,
        args.max_total_arm_travel_deg,
        args.max_total_gripper_travel,
        args.tracking_error_deg,
        args.tracking_error_gripper,
        args.grasp_contact_min_position,
        args.grasp_contact_load_percent,
        args.grasp_contact_confirm_s,
        args.grasp_hold_offset,
        args.grasp_release_position,
        args.grasp_release_confirm_s,
        args.grasp_max_hold_s,
        args.grasp_max_temperature_c,
    )
    if args.steps <= 0 or any(
        not math.isfinite(value) or value <= 0 for value in positive
    ):
        raise SystemExit("steps, rates and safety limits must be positive")
    if args.wrist_support_recovery_deg_s > args.max_wrist_speed_deg_s:
        raise SystemExit("wrist recovery speed cannot exceed the wrist speed limit")
    if args.grasp_contact_current_raw < 0:
        raise SystemExit("grasp contact current threshold cannot be negative")
    if args.grasp_release_position <= args.grasp_contact_min_position:
        raise SystemExit("grasp release position must exceed contact position threshold")
    if args.max_total_elbow_travel_deg is not None and (
        not math.isfinite(args.max_total_elbow_travel_deg)
        or args.max_total_elbow_travel_deg <= 0
    ):
        raise SystemExit("elbow travel override must be positive")
    if not args.checkpoint.is_dir() or not args.dataset_root.is_dir():
        raise SystemExit("checkpoint and dataset root must exist")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but is unavailable")
    if args.execute and not sys.stdin.isatty():
        raise SystemExit("interactive TTY required for --execute")

    from act_checkpoint_dry_run import (
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
    if args.steps > 2000:
        raise SystemExit("--steps above 2000 requires a separately reviewed long-rollout gate")
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
    wrist_state_index = state_names.index("wrist_roll.pos")
    wrist_state_lower = state_minimum[wrist_state_index]
    wrist_state_upper = state_maximum[wrist_state_index]
    if args.wrist_support_margin_deg * 2 >= wrist_state_upper - wrist_state_lower:
        raise SystemExit("wrist support margin leaves no usable training interval")
    rollout_action_minimum, rollout_action_maximum = (
        intersect_position_action_with_state_bounds(
            action_names,
            action_minimum,
            action_maximum,
            state_names,
            state_minimum,
            state_maximum,
        )
    )

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
        position_state = positions(robot.get_observation())
        position_wrist_raw = raw_wrist(robot.bus)
        if args.start_from_current:
            print(
                "CONTINUATION MODE：跳过 folded 起点检查；将使用当前姿态和最新画面"
                "生成下一个 ACT 动作块。"
            )
        else:
            folded_reference, folded_wrist_raw = load_folded_pose(
                args.folded_pose_json
            )
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
        initial_gripper_health: dict[str, int | None] | None = None
        if args.grasp_supervisor:
            initial_gripper_health = read_gripper_side_channel(
                robot.bus, health=True
            )
            if initial_gripper_health["status_raw"] != 0:
                raise RuntimeError(
                    "gripper status register is nonzero before rollout "
                    f"({initial_gripper_health['status_raw']})"
                )
            if (
                initial_gripper_health["temperature_c"] is not None
                and initial_gripper_health["temperature_c"]
                >= args.grasp_max_temperature_c
            ):
                raise RuntimeError(
                    "gripper temperature is already "
                    f"{initial_gripper_health['temperature_c']}°C"
                )

        gemini.start()
        wrist_camera.start()
        cameras_started = True

        def observation_from_live(current_state: dict[str, float]) -> dict[str, torch.Tensor]:
            values = state_values(current_state, state_names)
            model_values, _ = clamp_rollout_live_state(
                values,
                state_minimum,
                state_maximum,
                state_names,
                args.max_state_range_tolerance,
                args.max_wrist_state_range_tolerance,
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
        first_guarded, first_reasons = rollout_guarded_action(
            first_predicted,
            action_names,
            rollout_action_minimum,
            rollout_action_maximum,
            {joint: start_state[joint] for joint in POSITION_JOINTS},
            start_state,
            args.max_arm_step_deg,
            args.max_gripper_step,
            args.max_wrist_speed_deg_s,
            args.tracking_error_deg,
            args.tracking_error_gripper,
        )
        print("ACT 短 rollout 已准备；目前仍为松扭矩。")
        print(
            json.dumps(
                {
                    "steps": args.steps,
                    "duration_s": args.steps / args.fps,
                    "start_mode": (
                        "current_continuation"
                        if args.start_from_current
                        else "saved_folded_pose"
                    ),
                    "chunk_size": int(config.chunk_size),
                    "n_action_steps": int(config.n_action_steps),
                    "planned_policy_chunks": math.ceil(
                        args.steps / int(config.n_action_steps)
                    ),
                    "total_travel_limits_deg": {
                        "arm_default": args.max_total_arm_travel_deg,
                        "elbow_flex": (
                            args.max_total_elbow_travel_deg
                            if args.max_total_elbow_travel_deg is not None
                            else args.max_total_arm_travel_deg
                        ),
                        "gripper": args.max_total_gripper_travel,
                    },
                    "start_state": start_state,
                    "first_predicted": action_dict(action_names, first_predicted),
                    "first_guarded": first_guarded,
                    "first_guard_reasons": first_reasons,
                    "grasp_supervisor": {
                        "enabled": args.grasp_supervisor,
                        "minimum_position": args.grasp_contact_min_position,
                        "minimum_load_percent": args.grasp_contact_load_percent,
                        "minimum_current_raw": args.grasp_contact_current_raw,
                        "confirmation_s": args.grasp_contact_confirm_s,
                        "hold_offset": args.grasp_hold_offset,
                        "release_position": args.grasp_release_position,
                        "release_confirmation_s": args.grasp_release_confirm_s,
                        "maximum_hold_s": args.grasp_max_hold_s,
                        "initial_health": initial_gripper_health,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        if not args.execute:
            print("DRY RUN：未启用扭矩或发送动作。添加 --execute 才允许短 rollout。")
            return 0
        confirmation = "CONTINUE" if args.start_from_current else "ROLLOUT"
        if input(
            "清空白臂全程运动空间并保持可立即断开12V；"
            f"输入 {confirmation} 执行："
        ).strip() != confirmation:
            print("已取消；没有启用扭矩或发送动作。")
            return 0

        robot.bus.enable_torque(list(POSITION_JOINTS))
        torque_enabled = True
        robot.bus.enable_torque(WRIST)
        period = 1.0 / args.fps
        trace = []
        grasp_supervisor = (
            GripperContactSupervisor(
                minimum_position=args.grasp_contact_min_position,
                minimum_load_percent=args.grasp_contact_load_percent,
                minimum_current_raw=args.grasp_contact_current_raw,
                confirmation_s=args.grasp_contact_confirm_s,
                hold_offset=args.grasp_hold_offset,
                release_position=args.grasp_release_position,
                release_confirmation_s=args.grasp_release_confirm_s,
                maximum_hold_s=args.grasp_max_hold_s,
            )
            if args.grasp_supervisor
            else None
        )
        last_command = {joint: start_state[joint] for joint in POSITION_JOINTS}
        maximum_tracking_error = {joint: 0.0 for joint in POSITION_JOINTS}
        grasp_event_counts = {"contact_latched": 0, "contact_released": 0}
        for step_index in range(args.steps):
            loop_started = time.monotonic()
            current_state, current_raw = positions_from_single_raw_sync(robot)
            predicted = (
                first_predicted
                if step_index == 0
                else next_policy_action(observation_from_live(current_state))
            )
            command, reasons = rollout_guarded_action(
                predicted,
                action_names,
                rollout_action_minimum,
                rollout_action_maximum,
                last_command,
                current_state,
                args.max_arm_step_deg,
                args.max_gripper_step,
                args.max_wrist_speed_deg_s,
                args.tracking_error_deg,
                args.tracking_error_gripper,
            )
            position_command = {
                joint: command[f"{joint}.pos"] for joint in POSITION_JOINTS
            }
            position_command, total_envelope_clamps = (
                clamp_position_to_total_envelope(
                    position_command,
                    start_state,
                    args.max_total_arm_travel_deg,
                    args.max_total_gripper_travel,
                    args.max_total_elbow_travel_deg,
                )
            )
            for joint in total_envelope_clamps:
                command[f"{joint}.pos"] = position_command[joint]
                reasons.setdefault(f"{joint}.pos", []).append("total_travel")
            gripper_side_channel: dict[str, int | None] | None = None
            grasp_supervisor_state: dict[str, object] | None = None
            if grasp_supervisor is not None:
                gripper_side_channel = read_gripper_side_channel(
                    robot.bus,
                    health=step_index % max(1, int(args.fps)) == 0,
                )
                if (
                    gripper_side_channel["temperature_c"] is not None
                    and gripper_side_channel["temperature_c"]
                    >= args.grasp_max_temperature_c
                ):
                    raise RuntimeError(
                        "gripper temperature reached "
                        f"{gripper_side_channel['temperature_c']}°C"
                    )
                if gripper_side_channel["status_raw"] not in (None, 0):
                    raise RuntimeError(
                        "gripper status register became nonzero "
                        f"({gripper_side_channel['status_raw']})"
                    )
                grasp_supervisor_state = grasp_supervisor.update(
                    now_s=time.monotonic(),
                    present_position=current_state["gripper"],
                    requested_position=position_command["gripper"],
                    policy_requested_position=action_dict(
                        action_names, predicted
                    )["gripper.pos"],
                    load_raw=int(gripper_side_channel["load_raw"]),
                    current_raw=int(gripper_side_channel["current_raw"]),
                )
                position_command["gripper"] = float(
                    grasp_supervisor_state["guarded_position"]
                )
                command["gripper.pos"] = position_command["gripper"]
                if grasp_supervisor_state["guard_reason"] is not None:
                    reasons.setdefault("gripper.pos", []).append(
                        str(grasp_supervisor_state["guard_reason"])
                    )
                if grasp_supervisor_state["event"] is not None:
                    grasp_event_counts[str(grasp_supervisor_state["event"])] += 1
                    print(
                        "\nGRASP_CONTACT_"
                        + str(grasp_supervisor_state["event"])
                        .removeprefix("contact_")
                        .upper()
                        + " "
                        + json.dumps(grasp_supervisor_state, ensure_ascii=False)
                    )
            wrist_speed = command["wrist_roll.vel_deg_s"]
            wrist_speed, wrist_support_reason = keep_wrist_velocity_inside_state_support(
                wrist_speed,
                current_state[WRIST],
                wrist_state_lower,
                wrist_state_upper,
                args.wrist_support_margin_deg,
                args.wrist_support_recovery_deg_s,
            )
            if wrist_support_reason is not None:
                command["wrist_roll.vel_deg_s"] = wrist_speed
                reasons.setdefault("wrist_roll.vel_deg_s", []).append(
                    wrist_support_reason
                )
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
                args.tracking_error_deg,
                args.tracking_error_gripper,
                args.max_total_elbow_travel_deg,
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
                limit = (
                    args.tracking_error_gripper
                    if joint == "gripper"
                    else args.tracking_error_deg
                )
                if error > limit + 1e-6:
                    raise RuntimeError(
                        f"tracking error {error:.1f} on {joint} exceeds {limit:.1f}"
                    )
            trace.append(
                {
                    "step": step_index,
                    "state": current_state,
                    "predicted": action_dict(action_names, predicted),
                    "command": command,
                    "guard_reasons": reasons,
                    "gripper_side_channel": gripper_side_channel,
                    "grasp_supervisor": grasp_supervisor_state,
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
            args.tracking_error_deg,
            args.tracking_error_gripper,
            args.max_total_elbow_travel_deg,
        )
        if final_violations:
            detail = ", ".join(
                f"{joint}={delta:+.1f}" for joint, delta in final_violations.items()
            )
            raise RuntimeError(f"final rollout travel limit exceeded: {detail}")
        chunk_summaries = summarize_policy_chunks(
            trace,
            int(config.n_action_steps),
            final_state,
        )
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
                    "chunk_summaries": chunk_summaries,
                    "grasp_supervisor_summary": {
                        "enabled": grasp_supervisor is not None,
                        "event_counts": grasp_event_counts,
                        "latched_at_end": (
                            grasp_supervisor.latched
                            if grasp_supervisor is not None
                            else False
                        ),
                        "contact_position_at_end": (
                            grasp_supervisor.contact_position
                            if grasp_supervisor is not None
                            else None
                        ),
                    },
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
