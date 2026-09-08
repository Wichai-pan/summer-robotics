#!/usr/bin/env python3
"""Record pick-and-stow demonstrations, then keep the white arm holding.

Five joints use relative position following. ``wrist_roll`` is the exception:
it uses a low-speed velocity loop so encoder wrap 4095/0 cannot become a
nearly full-turn position command.  No automatic absolute-pose alignment is
performed; place both arms in similar physical poses before starting.
"""

from __future__ import annotations

import argparse
import json
import math
import select
import signal
import sys
import termios
import time
import tty
from pathlib import Path

from manipulation_state_machine import State, StateMachine, pick_frames_enabled
from portutil import BOARDS, PortResolutionError, resolve_port
from wrist_roll_velocity_follow import (
    DEG_PER_TICK,
    ENCODER_TICKS,
    velocity_command_raw,
    wrapped_tick_delta,
)


WRIST = "wrist_roll"
POSITION_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "gripper",
)
ALL_JOINTS = (*POSITION_JOINTS[:-1], WRIST, POSITION_JOINTS[-1])
DEFAULT_ACT_TASK = (
    "Pick up the cup level, retract the white arm slightly, and maintain the grasp."
)
GLOBAL_ABORT_KEY = "x"


class OperatorAbort(RuntimeError):
    """The operator invalidated the current episode with the global abort key."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--black-port")
    parser.add_argument("--white-port")
    parser.add_argument("--black-id", default="black_arm")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument("--invert", nargs="*", choices=ALL_JOINTS, default=[])
    parser.add_argument("--duration-s", type=float, default=120.0)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--max-speed-deg-s", type=float, default=30.0)
    parser.add_argument("--max-gripper-speed-s", type=float, default=60.0)
    parser.add_argument("--tracking-error-deg", type=float, default=15.0)
    parser.add_argument("--full-range", action="store_true")
    parser.add_argument("--max-delta-deg", type=float, default=30.0)
    parser.add_argument("--max-gripper-delta", type=float, default=30.0)
    parser.add_argument("--wrist-max-speed-deg-s", type=float, default=8.0)
    parser.add_argument("--wrist-gain-per-s", type=float, default=1.5)
    parser.add_argument("--wrist-deadband-deg", type=float, default=1.5)
    parser.add_argument("--wrist-max-travel-deg", type=float, default=60.0)
    parser.add_argument("--max-hold-temperature-c", type=float, default=60.0)
    parser.add_argument("--max-hold-gripper-error", type=float, default=8.0)
    recording = parser.add_argument_group("optional ACT recording")
    recording.add_argument(
        "--record-root",
        type=Path,
        help="LeRobotDataset root (for example /data/act/fixed_pick_place_v1)",
    )
    recording.add_argument("--record-repo-id", default="forestbridge/fixed-pick-place-v1")
    recording.add_argument("--scene-version")
    recording.add_argument("--task", default=DEFAULT_ACT_TASK)
    recording.add_argument(
        "--white-wrist-device",
        help="container V4L2 path, e.g. /dev/wrist-2-4-1 (required with --record-root)",
    )
    recording.add_argument("--record-width", type=int, default=640)
    recording.add_argument("--record-height", type=int, default=480)
    recording.add_argument("--camera-fps", type=int, default=30)
    recording.add_argument("--max-camera-age-s", type=float, default=0.25)
    recording.add_argument(
        "--folded-pose-json",
        type=Path,
        help="fixed white-arm folded-pose reference (required with --record-root)",
    )
    recording.add_argument(
        "--carry-pose-json",
        type=Path,
        help="deprecated compatibility option; the manual h endpoint is used",
    )
    recording.add_argument("--folded-tolerance-deg", type=float, default=8.0)
    recording.add_argument("--folded-gripper-tolerance", type=float, default=10.0)
    return parser.parse_args()


def positions(observation: dict[str, object]) -> dict[str, float]:
    result = {
        key.removesuffix(".pos"): float(value)
        for key, value in observation.items()
        if key.endswith(".pos")
    }
    missing = [joint for joint in ALL_JOINTS if joint not in result]
    if missing:
        raise RuntimeError(f"missing joint observations: {missing}")
    return result


def raw_wrist(bus: object) -> int:
    return int(bus.read("Present_Position", WRIST, normalize=False)) % ENCODER_TICKS


def cyclic_angle_error_deg(current: float, reference: float) -> float:
    """Shortest signed difference for the cyclic wrist-roll joint."""
    return (current - reference + 180.0) % 360.0 - 180.0


def load_folded_pose(path: Path) -> tuple[dict[str, float], int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "forestbridge_white_folded_pose/v1":
        raise RuntimeError(f"unsupported folded-pose schema in {path}")
    pose = payload.get("pose")
    if not isinstance(pose, dict):
        raise RuntimeError(f"folded-pose file has no pose object: {path}")
    result = {joint: float(pose[joint]) for joint in ALL_JOINTS}
    if any(not math.isfinite(value) for value in result.values()):
        raise RuntimeError(f"folded-pose file contains a non-finite value: {path}")
    wrist_raw = int(payload.get("wrist_raw_diagnostic", -1))
    if not 0 <= wrist_raw < ENCODER_TICKS:
        raise RuntimeError(f"folded-pose file has no valid wrist_raw_diagnostic: {path}")
    return result, wrist_raw


def folded_pose_violations(
    current: dict[str, float],
    reference: dict[str, float],
    arm_tolerance_deg: float,
    gripper_tolerance: float,
    *,
    current_wrist_raw: int | None = None,
    reference_wrist_raw: int | None = None,
) -> dict[str, float]:
    violations = {}
    for joint in ALL_JOINTS:
        if joint == WRIST:
            if (current_wrist_raw is None) != (reference_wrist_raw is None):
                raise ValueError("both wrist raw values must be supplied together")
            if current_wrist_raw is not None:
                # The calibrated wrist angle is not stable around raw 4095/0:
                # reconnecting can represent one physical pose in a different
                # normalized branch. Raw ticks plus wrapped shortest distance
                # are the authoritative fixed-pose comparison.
                error = wrapped_tick_delta(current_wrist_raw, reference_wrist_raw) * DEG_PER_TICK
            else:
                error = cyclic_angle_error_deg(current[joint], reference[joint])
        else:
            error = current[joint] - reference[joint]
        tolerance = gripper_tolerance if joint == "gripper" else arm_tolerance_deg
        if abs(error) > tolerance:
            violations[joint] = error
    return violations


def normalized_bounds(robot: object, joint: str) -> tuple[float, float]:
    calibration = robot.calibration[joint]
    if joint == "gripper":
        return (0.0, 100.0)
    span = (calibration.range_max - calibration.range_min) * 360.0 / 4095.0
    return (-span / 2.0, span / 2.0)


def relative_position_targets(
    black_now: dict[str, float],
    black_start: dict[str, float],
    white_start: dict[str, float],
    signs: dict[str, float],
    bounds: dict[str, tuple[float, float]],
    full_range: bool,
    max_delta_deg: float,
    max_gripper_delta: float,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for joint in POSITION_JOINTS:
        delta = signs[joint] * (black_now[joint] - black_start[joint])
        if not full_range:
            limit = max_gripper_delta if joint == "gripper" else max_delta_deg
            delta = max(-limit, min(limit, delta))
        target = white_start[joint] + delta
        lower, upper = bounds[joint]
        result[joint] = max(lower, min(upper, target))
    return result


def slew_positions(
    command: dict[str, float],
    target: dict[str, float],
    arm_step: float,
    gripper_step: float,
) -> dict[str, float]:
    result = {}
    for joint in POSITION_JOINTS:
        step = gripper_step if joint == "gripper" else arm_step
        delta = max(-step, min(step, target[joint] - command[joint]))
        result[joint] = command[joint] + delta
    return result


def control_key_pressed() -> str | None:
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    return sys.stdin.read(1).lower() if readable else None


def configure_white_torque_free(white: object) -> None:
    from lerobot.motors.feetech import OperatingMode

    bus = white.bus
    bus.disable_torque()
    for joint in POSITION_JOINTS:
        bus.write("Operating_Mode", joint, OperatingMode.POSITION.value)
        bus.write("P_Coefficient", joint, 16)
        bus.write("I_Coefficient", joint, 0)
        bus.write("D_Coefficient", joint, 32)
    bus.write("Operating_Mode", WRIST, OperatingMode.VELOCITY.value)
    bus.write("Goal_Velocity", WRIST, 0, normalize=False)
    if int(bus.read("Goal_Velocity", WRIST, normalize=False)) != 0:
        raise RuntimeError("white wrist Goal_Velocity did not read back as zero")


def seed_position_goals_from_feedback(white: object) -> None:
    """Seed non-wrist goals in raw units and verify before enabling torque."""
    present = white.bus.sync_read(
        "Present_Position", POSITION_JOINTS, normalize=False
    )
    seeded = {}
    for joint, value in present.items():
        calibration = white.calibration[joint]
        seeded[joint] = max(calibration.range_min, min(calibration.range_max, int(value)))
    for joint, value in seeded.items():
        white.bus.write("Goal_Position", joint, value, normalize=False, num_retry=2)
        readback = int(white.bus.read("Goal_Position", joint, normalize=False, num_retry=2))
        if readback != value:
            raise RuntimeError(
                f"{joint} raw goal seed mismatch: wrote {value}, read {readback}"
            )


def main() -> int:
    args = parse_args()
    if args.record_root is None:
        raise SystemExit("pick-hold collection requires --record-root")
    positive = (
        args.duration_s,
        args.fps,
        args.max_speed_deg_s,
        args.max_gripper_speed_s,
        args.tracking_error_deg,
        args.max_delta_deg,
        args.max_gripper_delta,
        args.wrist_max_speed_deg_s,
        args.wrist_gain_per_s,
        args.wrist_deadband_deg,
        args.wrist_max_travel_deg,
        args.max_hold_temperature_c,
        args.max_hold_gripper_error,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("all timing, gain, speed, error and travel values must be positive")
    if args.record_root is not None:
        if (
            not args.scene_version
            or not args.white_wrist_device
            or not args.folded_pose_json
        ):
            raise SystemExit(
                "--record-root also requires --scene-version, --white-wrist-device, "
                "and --folded-pose-json"
            )
        if not float(args.fps).is_integer():
            raise SystemExit("LeRobotDataset recording requires an integer --fps")
        if args.record_width <= 0 or args.record_height <= 0 or args.camera_fps <= 0:
            raise SystemExit("recording dimensions and camera FPS must be positive")
        if not math.isfinite(args.max_camera_age_s) or args.max_camera_age_s <= 0:
            raise SystemExit("--max-camera-age-s must be positive")
        if args.folded_tolerance_deg <= 0 or args.folded_gripper_tolerance <= 0:
            raise SystemExit("folded-pose tolerances must be positive")
        if not args.folded_pose_json.is_file():
            raise SystemExit(f"folded-pose reference not found: {args.folded_pose_json}")
    if not sys.stdin.isatty():
        raise SystemExit("interactive TTY required; use jetson_robot_exec.sh --interactive")

    try:
        black_port = resolve_port(BOARDS["black"], override=args.black_port)
        white_port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if black_port == white_port:
        raise SystemExit("black and white ports resolved to the same device")

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    black = SO100Follower(
        SO100FollowerConfig(port=black_port, id=args.black_id, disable_torque_on_disconnect=True)
    )
    white = SO100Follower(
        SO100FollowerConfig(
            port=white_port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )
    black_connected = False
    white_connected = False
    white_enabled = False
    white_wrist_velocity_mode = False
    terminal_state = None
    recorder = None
    recorder_abort_reason = "process_ended_without_episode_decision"
    machine: StateMachine | None = None
    try:
        print(f"黑臂 leader（只读/松扭矩）：{black_port}")
        print(f"白臂 follower（执行）：{white_port}")
        black.bus.connect()
        black_connected = True
        black.bus.disable_torque()
        if not black.is_calibrated:
            raise RuntimeError(f"black motor registers do not match {args.black_id}")

        white.bus.connect()
        white_connected = True
        white.bus.disable_torque()
        if not white.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.white_id}")
        folded_reference = None
        folded_wrist_raw = None
        if args.record_root is not None:
            # The saved reference is captured while wrist_roll is in position
            # mode. Validate in that same mode: switching to velocity mode can
            # change which numeric branch Present_Position reports near 4095/0
            # even though the physical shaft did not move.
            folded_reference, folded_wrist_raw = load_folded_pose(args.folded_pose_json)
            white_folded_check = positions(white.get_observation())
            white_folded_wrist_raw = raw_wrist(white.bus)
            start_violations = folded_pose_violations(
                white_folded_check,
                folded_reference,
                args.folded_tolerance_deg,
                args.folded_gripper_tolerance,
                current_wrist_raw=white_folded_wrist_raw,
                reference_wrist_raw=folded_wrist_raw,
            )
            if start_violations:
                detail = ", ".join(
                    f"{joint}={error:+.1f}" for joint, error in start_violations.items()
                )
                raise RuntimeError(
                    "white arm is not at the fixed folded start pose; "
                    f"errors outside tolerance: {detail}"
                )
            print("固定收拢起点校验通过。")

        configure_white_torque_free(white)
        white_wrist_velocity_mode = True
        seed_position_goals_from_feedback(white)

        black_start = positions(black.get_observation())
        white_start = positions(white.get_observation())
        black_wrist_start = raw_wrist(black.bus)
        white_wrist_start = raw_wrist(white.bus)
        signs = {joint: (-1.0 if joint in args.invert else 1.0) for joint in ALL_JOINTS}
        bounds = {joint: normalized_bounds(white, joint) for joint in POSITION_JOINTS}

        if args.record_root is not None:
            from act_episode_recorder import ACTEpisodeRecorder

            print("\n启动 ACT recorder：Gemini RGB + 白臂 wrist RGB + 白臂 state/action。")
            print("此时只打开相机和数据集 writer；尚未给白臂上扭矩。")
            recorder = ACTEpisodeRecorder(
                root=args.record_root,
                repo_id=args.record_repo_id,
                task=args.task,
                scene_version=args.scene_version,
                fps=int(args.fps),
                width=args.record_width,
                height=args.record_height,
                camera_fps=args.camera_fps,
                white_wrist_device=args.white_wrist_device,
                max_camera_age_s=args.max_camera_age_s,
            )
            recorder.start()
            print(
                f"Recorder ready: {args.record_root} | {args.record_width}x{args.record_height} "
                f"| control={int(args.fps)} FPS | cameras={args.camera_fps} FPS"
            )

        print("\n相对跟随：当前两臂姿态分别作为各自零点，不做绝对角度对齐。")
        print("肩/肘/腕俯仰/夹爪使用位置跟随；wrist_roll 使用跨圈安全速度闭环。")
        print(
            f"腕部：≤{args.wrist_max_speed_deg_s:.1f}°/s，"
            f"累计≤{args.wrist_max_travel_deg:.1f}°；方向="
            f"{'反向' if signs[WRIST] < 0 else '同向'}。"
        )
        print("请先在断扭矩状态把两臂人工摆到相似姿态，并清空两臂运动空间。")
        machine = StateMachine(State.PREPARE_PICK)
        start_decision = input("输入 FOLLOW 才给白臂上扭矩并开始（输入 x 全局中止）：").strip()
        if start_decision.lower() == GLOBAL_ABORT_KEY:
            raise OperatorAbort("operator_global_abort_before_follow")
        if start_decision != "FOLLOW":
            print("已取消；白臂没有上扭矩。")
            return 0
        machine.transition(State.RECORD_PICK)

        white.bus.enable_torque(list(POSITION_JOINTS))
        white.bus.enable_torque(WRIST)
        white_enabled = True
        terminal_state = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())

        command = {joint: white_start[joint] for joint in POSITION_JOINTS}
        black_wrist_previous = black_wrist_start
        white_wrist_previous = white_wrist_start
        black_wrist_ticks = 0
        white_wrist_ticks = 0
        period = 1.0 / args.fps
        arm_step = args.max_speed_deg_s / args.fps
        gripper_step = args.max_gripper_speed_s / args.fps
        started = time.monotonic()
        last_print = -1.0
        hold_requested = False
        gripper_latched_command: float | None = None
        print(
            "状态 RECORD_PICK：量杯保持水平；确认已稳定抓起后按 v，"
            "稍微收臂到安全运输位置后按 h。v/h 均不再执行抓取或终点姿态判断。"
        )
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            key = control_key_pressed()
            if key == GLOBAL_ABORT_KEY:
                raise OperatorAbort(f"operator_global_abort_in_{machine.state.name.lower()}")
            if key == "h":
                if machine.state is not State.RETRACT_TO_HOLD:
                    print("\n拒绝 h：必须先在物品稳定抓起后按 v。")
                    continue
                white.bus.write("Goal_Velocity", WRIST, 0, normalize=False)
                hold_candidate = positions(white.get_observation())
                command = {joint: hold_candidate[joint] for joint in POSITION_JOINTS}
                white.bus.sync_write("Goal_Position", command)
                machine.transition(State.FINALIZE_PICK)
                print("\nh：已接受当前小幅收臂姿态；冻结全部关节并结束采集。")
                hold_requested = True
                break
            if key == "v":
                if machine.state is not State.RECORD_PICK:
                    print(f"\n状态 {machine.state.name} 不接受 v。")
                    continue
                gripper_latched_command = positions(white.get_observation())["gripper"]
                command["gripper"] = gripper_latched_command
                white.bus.sync_write("Goal_Position", command)
                machine.transition(State.RETRACT_TO_HOLD)
                print(
                    f"\nv：人工确认抓取成功；夹爪锁定在当前位置 "
                    f"{gripper_latched_command:.2f}。请保持量杯水平并稍微收臂，然后按 h。"
                )
                continue
            if key in {"q", "\x1b"}:
                print("\n录制期间 q/ESC 只会丢弃本 episode；不会进入持物保持。")
                recorder_abort_reason = "operator_cancelled_before_hold"
                return 0

            black_now = positions(black.get_observation())
            target = relative_position_targets(
                black_now,
                black_start,
                white_start,
                signs,
                bounds,
                args.full_range,
                args.max_delta_deg,
                args.max_gripper_delta,
            )
            if gripper_latched_command is not None:
                # v is the grasp-success boundary. Keep the actual gripper
                # position observed at that instant instead of following any
                # later leader squeeze during the short retract.
                target["gripper"] = gripper_latched_command
            command = slew_positions(command, target, arm_step, gripper_step)
            white.bus.sync_write("Goal_Position", command)

            black_wrist_raw = raw_wrist(black.bus)
            white_wrist_raw = raw_wrist(white.bus)
            black_step = wrapped_tick_delta(black_wrist_raw, black_wrist_previous)
            white_step = wrapped_tick_delta(white_wrist_raw, white_wrist_previous)
            black_wrist_previous = black_wrist_raw
            white_wrist_previous = white_wrist_raw
            max_feedback_step = int(round(45.0 / DEG_PER_TICK))
            if abs(black_step) > max_feedback_step or abs(white_step) > max_feedback_step:
                raise RuntimeError(
                    f"implausible wrist encoder jump: black={black_step}, white={white_step}"
                )
            black_wrist_ticks += black_step
            white_wrist_ticks += white_step
            wrist_requested_deg = signs[WRIST] * black_wrist_ticks * DEG_PER_TICK
            wrist_target_deg = max(
                -args.wrist_max_travel_deg,
                min(args.wrist_max_travel_deg, wrist_requested_deg),
            )
            wrist_actual_deg = white_wrist_ticks * DEG_PER_TICK
            if abs(wrist_actual_deg) > args.wrist_max_travel_deg + 10.0:
                raise RuntimeError(f"white wrist exceeded safety margin: {wrist_actual_deg:+.1f}°")
            wrist_error = wrist_target_deg - wrist_actual_deg
            wrist_velocity = velocity_command_raw(
                wrist_error,
                args.wrist_gain_per_s,
                args.wrist_max_speed_deg_s,
                args.wrist_deadband_deg,
            )
            white.bus.write("Goal_Velocity", WRIST, wrist_velocity, normalize=False)

            white_now = positions(white.get_observation())
            errors = {
                joint: abs(command[joint] - white_now[joint])
                for joint in POSITION_JOINTS
                if joint != "gripper"
            }
            worst = max(errors, key=errors.get)
            if errors[worst] > args.tracking_error_deg:
                raise RuntimeError(
                    f"tracking error {errors[worst]:.1f}° on {worst} "
                    f"> {args.tracking_error_deg:.1f}°"
                )

            elapsed = time.monotonic() - started
            if recorder is not None and pick_frames_enabled(machine.state):
                # Keep the cyclic joint continuous within the episode.  The
                # corresponding action is the actual velocity sent to motor 5;
                # the other five actions are the actual slewed position goals.
                white_record_state = dict(white_now)
                white_record_state[WRIST] = white_start[WRIST] + wrist_actual_deg
                black_record_state = dict(black_now)
                black_record_state[WRIST] = black_start[WRIST] + black_wrist_ticks * DEG_PER_TICK
                sent_action = dict(command)
                sent_action[WRIST] = wrist_velocity * DEG_PER_TICK
                signed_tracking_error = {
                    joint: command[joint] - white_now[joint] for joint in POSITION_JOINTS
                }
                signed_tracking_error[WRIST] = wrist_error
                recorder.add_control_frame(
                    white_state=white_record_state,
                    action=sent_action,
                    black_state=black_record_state,
                    tracking_error=signed_tracking_error,
                    control_elapsed_s=elapsed,
                )
            if elapsed - last_print >= 0.5:
                deltas = " ".join(
                    f"{joint}={command[joint] - white_start[joint]:+.1f}"
                    for joint in POSITION_JOINTS
                )
                print(
                    f"\r{elapsed:5.1f}s {deltas} wrist={wrist_actual_deg:+.1f}/"
                    f"{wrist_target_deg:+.1f}°"
                    + (
                        f" CLAMPED(request={wrist_requested_deg:+.1f}°)"
                        if wrist_requested_deg != wrist_target_deg
                        else ""
                    ),
                    end="",
                    flush=True,
                )
                last_print = elapsed

            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
        if not hold_requested:
            recorder_abort_reason = "recording_timeout_without_hold"
            print("\n录制超时但未收到 h；episode 已丢弃并执行安全松扭矩。")
            return 0
        assert recorder is not None
        recorder.stop_capture()
        print(
            "\n录制和两路相机均已停止；h 之后的等待和底盘运动不会进入 episode。"
            "本次数据暂不保存，只有安全结束 HOLD 后才会提交。"
        )
        white.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)

        # Operating mode changes require wrist torque off. Only wrist_roll is
        # briefly disabled; the arm and gripper remain actively holding.
        from lerobot.motors.feetech import OperatingMode

        hold_wrist_raw = raw_wrist(white.bus)
        white.bus.disable_torque(WRIST, num_retry=3)
        white.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
        white_wrist_velocity_mode = False
        white.bus.write("Goal_Position", WRIST, hold_wrist_raw, normalize=False, num_retry=3)
        white.bus.enable_torque(WRIST)

        hold_pose = positions(white.get_observation())
        hold_command = {joint: hold_pose[joint] for joint in POSITION_JOINTS}
        white.bus.sync_write("Goal_Position", hold_command)
        hold_wrist_raw = raw_wrist(white.bus)

        recorder_abort_reason = "hold_ended_without_success_confirmation"
        hold_failure_reason: str | None = None
        print("HOLD：白臂和夹爪保持上扭矩；相机已关闭，episode 等待最终确认。")
        machine.transition(State.HOLD)
        machine.transition(State.WAIT_FOR_PLACE)
        print(
            "状态 WAIT_FOR_PLACE：当前 h 姿态就是本次终点；"
            "不执行固定 carry、抓取负载或 wrist_roll 终点判断。"
        )
        print(
            "物品被可靠承接后按 r，再输入 RELEASE 保存并松扭矩；"
            "若掉落、碰撞或本次实验无效，随时按 x 全局中止并丢弃。"
        )
        previous_sigint = signal.getsignal(signal.SIGINT)

        def reject_sigint(_signum: int, _frame: object) -> None:
            print("\n拒绝 Ctrl-C：当前仍在持物 HOLD。请承接物品后按 r。")

        signal.signal(signal.SIGINT, reject_sigint)
        last_health = 0.0
        while True:
            loop_started = time.monotonic()
            white.bus.sync_write("Goal_Position", hold_command)
            white.bus.write("Goal_Position", WRIST, hold_wrist_raw, normalize=False)
            key = control_key_pressed()
            if key == GLOBAL_ABORT_KEY:
                raise OperatorAbort("operator_global_abort_during_hold")
            if key in {"q", "\x1b"}:
                print("\n持物期间 q/ESC 无效；按 x 可全局中止并丢弃本 episode。")
            elif key == "r":
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, terminal_state)
                terminal_state = None
                release_decision = input(
                    "确认物品已被可靠承接；输入 RELEASE 保存并解除保持，输入 x 丢弃："
                ).strip()
                if release_decision.lower() == GLOBAL_ABORT_KEY:
                    raise OperatorAbort("operator_global_abort_at_release_confirmation")
                if release_decision != "RELEASE":
                    print("未确认，继续 HOLD。")
                    terminal_state = termios.tcgetattr(sys.stdin.fileno())
                    tty.setcbreak(sys.stdin.fileno())
                    continue
                break
            now = time.monotonic()
            if now - last_health >= 1.0:
                hold_now = positions(white.get_observation())
                temperature = int(
                    white.bus.read("Present_Temperature", "gripper", normalize=False, num_retry=2)
                )
                load_raw = int(
                    white.bus.read("Present_Load", "gripper", normalize=False, num_retry=2)
                )
                current_raw = int(
                    white.bus.read("Present_Current", "gripper", normalize=False, num_retry=2)
                )
                gripper_error = hold_command["gripper"] - hold_now["gripper"]
                print(
                    f"\rHOLD gripper_error={gripper_error:+.1f} "
                    f"load_raw={load_raw} current_raw={current_raw} temp={temperature}°C",
                    end="",
                    flush=True,
                )
                if temperature >= args.max_hold_temperature_c:
                    print(f"\n警告：夹爪温度 {temperature}°C；请立即承接物品并按 r。")
                    if machine.state in {State.HOLD, State.WAIT_FOR_PLACE}:
                        machine.transition(State.FAULT)
                    hold_failure_reason = f"hold_temperature={temperature}C"
                if abs(gripper_error) > args.max_hold_gripper_error:
                    print(
                        f"\n警告：夹爪保持误差 {gripper_error:+.1f} 超限；"
                        "可能滑落，请立即承接物品并按 r。"
                    )
                    if machine.state in {State.HOLD, State.WAIT_FOR_PLACE}:
                        machine.transition(State.FAULT)
                    hold_failure_reason = f"hold_gripper_error={gripper_error:+.1f}"
                last_health = now
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        signal.signal(signal.SIGINT, previous_sigint)
        if hold_failure_reason is not None:
            result = recorder.finish(success=False, failure_reason=hold_failure_reason)
            print(f"episode 已丢弃并记录失败原因：{hold_failure_reason}")
        else:
            result = recorder.finish(success=True)
            print(
                f"episode 已保存并复核：episode={result['saved_episode_index']} "
                f"frames={result['captured_frames']}"
            )
        if machine.state is not State.DONE:
            machine.transition(State.DONE)
        white.bus.disable_torque(num_retry=3)
        white_enabled = False
        print("物品已确认承接；白臂已松开全部扭矩。")
        return 0
    except OperatorAbort as exc:
        recorder_abort_reason = str(exc)
        if machine is not None and machine.state not in {State.DONE, State.ABORTED}:
            machine.transition(State.ABORTED)
        print("\n全局中止 x：本 episode 已判定无效并丢弃；实验停止。")
        return 130
    except KeyboardInterrupt:
        print("\nCtrl-C：停止并松扭矩。")
        recorder_abort_reason = "keyboard_interrupt"
        return 130
    except Exception as exc:
        recorder_abort_reason = f"runtime_error: {exc}"
        raise
    finally:
        if terminal_state is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, terminal_state)
        if white_connected:
            if white_wrist_velocity_mode:
                try:
                    white.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
                except Exception as exc:
                    print(f"警告：腕部零速度写入失败，请切断 12V：{exc}", file=sys.stderr)
            if white_enabled:
                try:
                    white.bus.disable_torque(num_retry=3)
                    print("白臂已发送腕部零速度并松开全部扭矩。")
                except Exception as exc:
                    print(f"警告：白臂松扭矩失败，请切断 12V：{exc}", file=sys.stderr)
            try:
                from lerobot.motors.feetech import OperatingMode

                white.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            except Exception:
                pass
            white.bus.disconnect(disable_torque=False)
        if black_connected:
            black.bus.disconnect(disable_torque=False)
        if recorder is not None:
            recorder.abort(recorder_abort_reason)


if __name__ == "__main__":
    raise SystemExit(main())
