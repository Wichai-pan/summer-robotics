#!/usr/bin/env python3
"""Collect independent pick and place episodes in one torque-on robot session.

The pick cameras stop at ``h``.  The arm then holds every joint while the base
moves.  Pressing ``b`` opens fresh cameras and a different dataset for the
place episode, so navigation frames can never leak into either training task.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from black_leads_white_pick_hold import (
    ALL_JOINTS,
    POSITION_JOINTS,
    WRIST,
    OperatorAbort,
    configure_white_torque_free,
    control_key_pressed,
    folded_pose_violations,
    load_folded_pose,
    normalized_bounds,
    positions,
    raw_wrist,
    relative_position_targets,
    seed_position_goals_from_feedback,
    slew_positions,
)
from manipulation_state_machine import State, StateMachine, pick_frames_enabled, place_frames_enabled
from portutil import BOARDS, PortResolutionError, resolve_port
from wrist_roll_velocity_follow import DEG_PER_TICK, velocity_command_raw, wrapped_tick_delta


GLOBAL_ABORT_KEY = "x"
PICK_TASK = "Pick up the measuring cup level, retract slightly, and hold the grasp."
PLACE_TASK = "Move the held measuring cup to the target, release it, and return the empty arm."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--black-port")
    parser.add_argument("--white-port")
    parser.add_argument("--black-id", default="black_arm")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument("--invert", nargs="*", choices=ALL_JOINTS, default=[])
    parser.add_argument("--duration-s", type=float, default=120.0, help="limit for each recorded segment")
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

    recording = parser.add_argument_group("two independent ACT datasets")
    recording.add_argument("--pick-record-root", type=Path, required=True)
    recording.add_argument(
        "--pick-record-repo-id", default="forestbridge/pick-level-cup-retract-hold-v2"
    )
    recording.add_argument("--pick-scene-version", required=True)
    recording.add_argument("--pick-task", default=PICK_TASK)
    recording.add_argument("--place-record-root", type=Path, required=True)
    recording.add_argument(
        "--place-record-repo-id", default="forestbridge/place-level-cup-release-v2"
    )
    recording.add_argument("--place-scene-version", required=True)
    recording.add_argument("--place-task", default=PLACE_TASK)
    recording.add_argument("--white-wrist-device", required=True)
    recording.add_argument("--record-width", type=int, default=640)
    recording.add_argument("--record-height", type=int, default=480)
    recording.add_argument("--camera-fps", type=int, default=30)
    recording.add_argument("--max-camera-age-s", type=float, default=0.25)
    recording.add_argument("--folded-pose-json", type=Path, required=True)
    recording.add_argument("--folded-tolerance-deg", type=float, default=8.0)
    recording.add_argument("--folded-gripper-tolerance", type=float, default=10.0)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
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
        args.max_camera_age_s,
        args.folded_tolerance_deg,
        args.folded_gripper_tolerance,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("all timing, gain, speed, error and tolerance values must be positive")
    if not float(args.fps).is_integer():
        raise SystemExit("LeRobotDataset recording requires an integer --fps")
    if args.record_width <= 0 or args.record_height <= 0 or args.camera_fps <= 0:
        raise SystemExit("recording dimensions and camera FPS must be positive")
    if args.pick_record_root.resolve() == args.place_record_root.resolve():
        raise SystemExit("pick and place must use different --*-record-root directories")
    if not args.folded_pose_json.is_file():
        raise SystemExit(f"folded-pose reference not found: {args.folded_pose_json}")
    if not sys.stdin.isatty():
        raise SystemExit("interactive TTY required; use jetson_robot_exec.sh --interactive")


def make_recorder(args: argparse.Namespace, *, pick: bool) -> Any:
    from act_episode_recorder import ACTEpisodeRecorder

    return ACTEpisodeRecorder(
        root=args.pick_record_root if pick else args.place_record_root,
        repo_id=args.pick_record_repo_id if pick else args.place_record_repo_id,
        task=args.pick_task if pick else args.place_task,
        scene_version=args.pick_scene_version if pick else args.place_scene_version,
        fps=int(args.fps),
        width=args.record_width,
        height=args.record_height,
        camera_fps=args.camera_fps,
        white_wrist_device=args.white_wrist_device,
        max_camera_age_s=args.max_camera_age_s,
    )


def wait_for_mode_wrist_raw(
    bus: object,
    *,
    timeout_s: float = 1.0,
    settle_s: float = 0.08,
    sample_interval_s: float = 0.02,
) -> int:
    """Read a stable wrist position after an operating-mode coordinate change."""
    time.sleep(settle_s)
    deadline = time.monotonic() + timeout_s
    recent: list[int] = []
    while time.monotonic() < deadline:
        recent.append(raw_wrist(bus))
        recent = recent[-3:]
        if len(recent) == 3:
            anchor = recent[-1]
            if all(abs(wrapped_tick_delta(value, anchor)) <= 3 for value in recent):
                return anchor
        time.sleep(sample_interval_s)
    raise RuntimeError(
        f"wrist raw position did not stabilize after operating-mode switch: {recent}"
    )


def verify_register(bus: object, name: str, expected: int) -> None:
    actual = int(bus.read(name, WRIST, normalize=False, num_retry=3))
    if actual != expected:
        raise RuntimeError(
            f"wrist {name} mode-switch verification failed: expected {expected}, got {actual}"
        )


def wrist_to_position_hold(white: object) -> int:
    from lerobot.motors.feetech import OperatingMode

    white.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
    verify_register(white.bus, "Goal_Velocity", 0)
    velocity_mode_raw = raw_wrist(white.bus)
    white.bus.disable_torque(WRIST, num_retry=3)
    white.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
    verify_register(white.bus, "Operating_Mode", OperatingMode.POSITION.value)

    # STS3215 Present_Position uses a different numeric coordinate when an
    # installed homing offset crosses POSITION/VELOCITY modes.  Never reuse
    # the velocity-mode raw value as a position goal: read the same physical
    # pose again after the mode switch and seed that coordinate instead.
    position_mode_raw = wait_for_mode_wrist_raw(white.bus)
    white.bus.write(
        "Goal_Position", WRIST, position_mode_raw, normalize=False, num_retry=3
    )
    verify_register(white.bus, "Goal_Position", position_mode_raw)
    white.bus.enable_torque(WRIST)
    coordinate_shift = wrapped_tick_delta(position_mode_raw, velocity_mode_raw)
    print(
        f"腕部已安全切换为位置保持：raw {velocity_mode_raw} -> {position_mode_raw} "
        f"（模式坐标偏移 {coordinate_shift:+d} ticks，不是运动命令）。"
    )
    return position_mode_raw


def wrist_to_velocity_follow(white: object) -> None:
    from lerobot.motors.feetech import OperatingMode

    position_mode_raw = raw_wrist(white.bus)
    white.bus.write(
        "Goal_Position", WRIST, position_mode_raw, normalize=False, num_retry=3
    )
    verify_register(white.bus, "Goal_Position", position_mode_raw)
    white.bus.disable_torque(WRIST, num_retry=3)
    white.bus.write("Operating_Mode", WRIST, OperatingMode.VELOCITY.value)
    verify_register(white.bus, "Operating_Mode", OperatingMode.VELOCITY.value)
    white.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
    verify_register(white.bus, "Goal_Velocity", 0)
    velocity_mode_raw = wait_for_mode_wrist_raw(white.bus)
    white.bus.enable_torque(WRIST)
    coordinate_shift = wrapped_tick_delta(velocity_mode_raw, position_mode_raw)
    print(
        f"腕部已安全切换为速度跟随：raw {position_mode_raw} -> {velocity_mode_raw} "
        f"（模式坐标偏移 {coordinate_shift:+d} ticks，不是运动命令）。"
    )


@dataclass
class FollowSample:
    white_now: dict[str, float]
    command: dict[str, float]
    wrist_actual_deg: float
    wrist_target_deg: float
    wrist_requested_deg: float


class RelativeFollower:
    def __init__(self, black: object, white: object, args: argparse.Namespace) -> None:
        self.black = black
        self.white = white
        self.args = args
        self.signs = {
            joint: (-1.0 if joint in args.invert else 1.0) for joint in ALL_JOINTS
        }
        self.bounds = {joint: normalized_bounds(white, joint) for joint in POSITION_JOINTS}
        self.arm_step = args.max_speed_deg_s / args.fps
        self.gripper_step = args.max_gripper_speed_s / args.fps
        self.locked_gripper: float | None = None
        self.rebase()

    def rebase(self) -> None:
        self.black_start = positions(self.black.get_observation())
        self.white_start = positions(self.white.get_observation())
        self.black_wrist_previous = raw_wrist(self.black.bus)
        self.white_wrist_previous = raw_wrist(self.white.bus)
        self.black_wrist_ticks = 0
        self.white_wrist_ticks = 0
        self.command = {joint: self.white_start[joint] for joint in POSITION_JOINTS}
        self.locked_gripper = None

    def latch_gripper_from_feedback(self) -> float:
        self.locked_gripper = positions(self.white.get_observation())["gripper"]
        self.command["gripper"] = self.locked_gripper
        self.white.bus.sync_write("Goal_Position", self.command)
        return self.locked_gripper

    def step(self, recorder: Any, *, elapsed: float, record: bool) -> FollowSample:
        black_now = positions(self.black.get_observation())
        target = relative_position_targets(
            black_now,
            self.black_start,
            self.white_start,
            self.signs,
            self.bounds,
            self.args.full_range,
            self.args.max_delta_deg,
            self.args.max_gripper_delta,
        )
        if self.locked_gripper is not None:
            target["gripper"] = self.locked_gripper
        self.command = slew_positions(
            self.command, target, self.arm_step, self.gripper_step
        )
        self.white.bus.sync_write("Goal_Position", self.command)

        black_wrist_raw = raw_wrist(self.black.bus)
        white_wrist_raw = raw_wrist(self.white.bus)
        black_step = wrapped_tick_delta(black_wrist_raw, self.black_wrist_previous)
        white_step = wrapped_tick_delta(white_wrist_raw, self.white_wrist_previous)
        self.black_wrist_previous = black_wrist_raw
        self.white_wrist_previous = white_wrist_raw
        max_feedback_step = int(round(45.0 / DEG_PER_TICK))
        if abs(black_step) > max_feedback_step or abs(white_step) > max_feedback_step:
            raise RuntimeError(
                f"implausible wrist encoder jump: black={black_step}, white={white_step}"
            )
        self.black_wrist_ticks += black_step
        self.white_wrist_ticks += white_step
        wrist_requested_deg = (
            self.signs[WRIST] * self.black_wrist_ticks * DEG_PER_TICK
        )
        wrist_target_deg = max(
            -self.args.wrist_max_travel_deg,
            min(self.args.wrist_max_travel_deg, wrist_requested_deg),
        )
        wrist_actual_deg = self.white_wrist_ticks * DEG_PER_TICK
        if abs(wrist_actual_deg) > self.args.wrist_max_travel_deg + 10.0:
            raise RuntimeError(
                f"white wrist exceeded safety margin: {wrist_actual_deg:+.1f}°"
            )
        wrist_error = wrist_target_deg - wrist_actual_deg
        wrist_velocity = velocity_command_raw(
            wrist_error,
            self.args.wrist_gain_per_s,
            self.args.wrist_max_speed_deg_s,
            self.args.wrist_deadband_deg,
        )
        self.white.bus.write("Goal_Velocity", WRIST, wrist_velocity, normalize=False)

        white_now = positions(self.white.get_observation())
        errors = {
            joint: abs(self.command[joint] - white_now[joint])
            for joint in POSITION_JOINTS
            if joint != "gripper"
        }
        worst = max(errors, key=errors.get)
        if errors[worst] > self.args.tracking_error_deg:
            raise RuntimeError(
                f"tracking error {errors[worst]:.1f}° on {worst} "
                f"> {self.args.tracking_error_deg:.1f}°"
            )

        if record:
            white_record_state = dict(white_now)
            white_record_state[WRIST] = self.white_start[WRIST] + wrist_actual_deg
            black_record_state = dict(black_now)
            black_record_state[WRIST] = (
                self.black_start[WRIST] + self.black_wrist_ticks * DEG_PER_TICK
            )
            sent_action = dict(self.command)
            sent_action[WRIST] = wrist_velocity * DEG_PER_TICK
            tracking_error = {
                joint: self.command[joint] - white_now[joint]
                for joint in POSITION_JOINTS
            }
            tracking_error[WRIST] = wrist_error
            recorder.add_control_frame(
                white_state=white_record_state,
                action=sent_action,
                black_state=black_record_state,
                tracking_error=tracking_error,
                control_elapsed_s=elapsed,
            )
        return FollowSample(
            white_now=white_now,
            command=dict(self.command),
            wrist_actual_deg=wrist_actual_deg,
            wrist_target_deg=wrist_target_deg,
            wrist_requested_deg=wrist_requested_deg,
        )


def print_follow_status(elapsed: float, follower: RelativeFollower, sample: FollowSample) -> None:
    deltas = " ".join(
        f"{joint}={sample.command[joint] - follower.white_start[joint]:+.1f}"
        for joint in POSITION_JOINTS
    )
    clamped = (
        f" CLAMPED(request={sample.wrist_requested_deg:+.1f}°)"
        if sample.wrist_requested_deg != sample.wrist_target_deg
        else ""
    )
    print(
        f"\r{elapsed:5.1f}s {deltas} wrist={sample.wrist_actual_deg:+.1f}/"
        f"{sample.wrist_target_deg:+.1f}°{clamped}",
        end="",
        flush=True,
    )


def main() -> int:
    args = parse_args()
    validate_args(args)
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
    pick_recorder = None
    place_recorder = None
    pick_abort_reason = "process_ended_without_pick_decision"
    place_abort_reason = "place_not_started"
    pick_saved = False
    place_saved = False
    machine: StateMachine | None = None
    previous_sigint = None

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

        folded_reference, folded_wrist_raw = load_folded_pose(args.folded_pose_json)
        start_pose = positions(white.get_observation())
        start_wrist_raw = raw_wrist(white.bus)
        violations = folded_pose_violations(
            start_pose,
            folded_reference,
            args.folded_tolerance_deg,
            args.folded_gripper_tolerance,
            current_wrist_raw=start_wrist_raw,
            reference_wrist_raw=folded_wrist_raw,
        )
        if violations:
            detail = ", ".join(f"{joint}={error:+.1f}" for joint, error in violations.items())
            raise RuntimeError(
                "white arm is not at the fixed empty start pose; "
                f"errors outside tolerance: {detail}"
            )
        print("固定空载起点校验通过。")

        configure_white_torque_free(white)
        white_wrist_velocity_mode = True
        seed_position_goals_from_feedback(white)

        print("\n启动夹取 recorder；放下 recorder 此时尚未创建。")
        pick_recorder = make_recorder(args, pick=True)
        pick_recorder.start()
        print(f"夹取 Recorder ready: {args.pick_record_root}")
        print("请在断扭矩状态把两臂人工摆到相似姿态，并清空运动空间。")
        machine = StateMachine(State.PREPARE_PICK)
        decision = input("输入 FOLLOW 开始夹取（输入 x 全局中止）：").strip()
        if decision.lower() == GLOBAL_ABORT_KEY:
            raise OperatorAbort("operator_global_abort_before_follow")
        if decision != "FOLLOW":
            print("已取消；白臂没有上扭矩。")
            return 0
        machine.transition(State.RECORD_PICK)

        white.bus.enable_torque(list(POSITION_JOINTS))
        white.bus.enable_torque(WRIST)
        white_enabled = True
        terminal_state = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        follower = RelativeFollower(black, white, args)
        period = 1.0 / args.fps
        started = time.monotonic()
        last_print = -1.0
        hold_requested = False
        print("状态 RECORD_PICK：稳定抓起后按 v，保持量杯水平稍微收臂后按 h。")
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            key = control_key_pressed()
            if key == GLOBAL_ABORT_KEY:
                raise OperatorAbort(f"operator_global_abort_in_{machine.state.name.lower()}")
            if key == "v":
                if machine.state is not State.RECORD_PICK:
                    print(f"\n状态 {machine.state.name} 不接受 v。")
                    continue
                latched = follower.latch_gripper_from_feedback()
                machine.transition(State.RETRACT_TO_HOLD)
                print(f"\nv：直接确认抓取成功；夹爪锁定 {latched:.2f}。稍微收臂后按 h。")
                continue
            if key == "h":
                if machine.state is not State.RETRACT_TO_HOLD:
                    print("\n拒绝 h：必须先按 v。")
                    continue
                white.bus.write("Goal_Velocity", WRIST, 0, normalize=False)
                hold_pose = positions(white.get_observation())
                hold_command = {joint: hold_pose[joint] for joint in POSITION_JOINTS}
                white.bus.sync_write("Goal_Position", hold_command)
                machine.transition(State.FINALIZE_PICK)
                hold_requested = True
                break
            if key in {"q", "\x1b"}:
                pick_abort_reason = "operator_cancelled_before_hold"
                print("\n夹取录制已取消，本片段丢弃。")
                return 0

            elapsed = time.monotonic() - started
            sample = follower.step(
                pick_recorder,
                elapsed=elapsed,
                record=pick_frames_enabled(machine.state),
            )
            if elapsed - last_print >= 0.5:
                print_follow_status(elapsed, follower, sample)
                last_print = elapsed
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        if not hold_requested:
            pick_abort_reason = "pick_timeout_without_hold"
            print("\n夹取超时且没有按 h；夹取片段丢弃。")
            return 0

        pick_recorder.stop_capture()
        print("\nh：夹取录像和相机已完全停止；底盘移动不会写入任何训练帧。")
        hold_wrist_raw = wrist_to_position_hold(white)
        white_wrist_velocity_mode = False
        hold_pose = positions(white.get_observation())
        hold_command = {joint: hold_pose[joint] for joint in POSITION_JOINTS}
        white.bus.sync_write("Goal_Position", hold_command)
        machine.transition(State.HOLD)
        machine.transition(State.WAIT_FOR_PLACE)
        pick_abort_reason = "pick_hold_aborted_before_place_start"

        previous_sigint = signal.getsignal(signal.SIGINT)

        def reject_sigint(_signum: int, _frame: object) -> None:
            print("\n当前正在持物。请用 x 丢弃，或到达放置位置后按 b。")

        signal.signal(signal.SIGINT, reject_sigint)
        print(
            "HOLD：全部关节和夹爪保持上扭矩。到达放置位置、确认物品仍稳定后按 b；"
            "按 b 前先把黑臂放到便于示教放下动作的姿态；掉落或本次无效按 x。"
        )
        last_health = 0.0
        while True:
            loop_started = time.monotonic()
            white.bus.sync_write("Goal_Position", hold_command)
            white.bus.write("Goal_Position", WRIST, hold_wrist_raw, normalize=False)
            key = control_key_pressed()
            if key == GLOBAL_ABORT_KEY:
                raise OperatorAbort("operator_global_abort_during_navigation_hold")
            if key == "b":
                break
            if key is not None:
                print("\nHOLD 只接受 b（开始放下）或 x（丢弃并中止）。")
            now = time.monotonic()
            if now - last_health >= 1.0:
                hold_now = positions(white.get_observation())
                temperature = int(
                    white.bus.read("Present_Temperature", "gripper", normalize=False, num_retry=2)
                )
                gripper_error = hold_command["gripper"] - hold_now["gripper"]
                print(
                    f"\rHOLD gripper_error={gripper_error:+.1f} temp={temperature}°C",
                    end="",
                    flush=True,
                )
                if temperature >= args.max_hold_temperature_c:
                    raise RuntimeError(f"hold gripper temperature too high: {temperature}C")
                if abs(gripper_error) > args.max_hold_gripper_error:
                    raise RuntimeError(f"hold gripper error too large: {gripper_error:+.1f}")
                last_health = now
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
            previous_sigint = None
        print("\nb：正在启动独立的放下 recorder；机械臂继续保持。")
        place_recorder = make_recorder(args, pick=False)
        place_abort_reason = "place_recorder_started_without_finish"
        place_recorder.start()
        print(f"放下 Recorder ready: {args.place_record_root}")

        pick_result = pick_recorder.finish(success=True)
        pick_saved = True
        print(
            f"夹取 episode 已独立保存：episode={pick_result['saved_episode_index']} "
            f"frames={pick_result['captured_frames']}"
        )

        wrist_to_velocity_follow(white)
        white_wrist_velocity_mode = True
        follower.rebase()
        machine.transition(State.PREPARE_PLACE)
        machine.transition(State.RECORD_PLACE)
        started = time.monotonic()
        last_print = -1.0
        place_finished = False
        print(
            "状态 RECORD_PLACE：放稳并由桌面支撑后按 p；打开夹爪后按 o；"
            "空载回到固定收拢姿态后按 q。p/o 为人工直接确认。"
        )
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            key = control_key_pressed()
            if key == GLOBAL_ABORT_KEY:
                raise OperatorAbort(f"operator_global_abort_in_{machine.state.name.lower()}")
            if key == "p":
                if machine.state is not State.RECORD_PLACE:
                    print(f"\n状态 {machine.state.name} 不接受 p。")
                    continue
                machine.transition(State.VERIFY_PLACE)
                machine.transition(State.VERIFY_RELEASE)
                print("\np：人工确认量杯已被桌面稳定支撑；请打开夹爪，完成后按 o。")
                continue
            if key == "o":
                if machine.state is not State.VERIFY_RELEASE:
                    print("\n拒绝 o：必须先按 p。")
                    continue
                machine.transition(State.RETURN_EMPTY)
                print("\no：人工确认已经松开量杯；请空载回到固定收拢姿态，然后按 q。")
                continue
            if key == "q":
                if machine.state is not State.RETURN_EMPTY:
                    print("\n拒绝 q：必须依次完成 p 和 o。")
                    continue
                machine.transition(State.VERIFY_EMPTY)
                final_pose = positions(white.get_observation())
                final_wrist_raw = raw_wrist(white.bus)
                violations = folded_pose_violations(
                    final_pose,
                    folded_reference,
                    args.folded_tolerance_deg,
                    args.folded_gripper_tolerance,
                    current_wrist_raw=final_wrist_raw,
                    reference_wrist_raw=folded_wrist_raw,
                )
                if violations:
                    machine.transition(State.RETURN_EMPTY)
                    detail = ", ".join(
                        f"{joint}={error:+.1f}" for joint, error in violations.items()
                    )
                    print(f"\n空载终点检查未通过：{detail}；继续调整后再按 q。")
                    continue
                machine.transition(State.FINALIZE_PLACE)
                place_finished = True
                break
            if key == "\x1b":
                place_abort_reason = "operator_cancelled_place"
                print("\n放下片段已取消；夹取片段已经独立保存。")
                return 0

            elapsed = time.monotonic() - started
            sample = follower.step(
                place_recorder,
                elapsed=elapsed,
                record=place_frames_enabled(machine.state),
            )
            if elapsed - last_print >= 0.5:
                print_follow_status(elapsed, follower, sample)
                last_print = elapsed
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        if not place_finished:
            place_abort_reason = "place_timeout_without_finish"
            print("\n放下录制超时；只丢弃放下片段，已保存的夹取片段保留。")
            return 0

        white.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
        wrist_to_position_hold(white)
        white_wrist_velocity_mode = False
        place_recorder.stop_capture()
        place_result = place_recorder.finish(success=True)
        place_saved = True
        machine.transition(State.DONE)
        print(
            f"\n放下 episode 已独立保存：episode={place_result['saved_episode_index']} "
            f"frames={place_result['captured_frames']}"
        )
        print("两段数据位于不同数据集，训练时互不连续。")
        white.bus.disable_torque(num_retry=3)
        white_enabled = False
        print("白臂已松开全部扭矩。")
        return 0

    except OperatorAbort as exc:
        reason = str(exc)
        if machine is not None and machine.state not in {State.DONE, State.ABORTED}:
            machine.transition(State.ABORTED)
        if pick_saved:
            print("\n全局中止 x：夹取片段已保存；当前放下片段已丢弃。")
        else:
            pick_abort_reason = reason
            print("\n全局中止 x：尚未提交的夹取片段已丢弃。")
        place_abort_reason = reason
        return 130
    except KeyboardInterrupt:
        pick_abort_reason = "keyboard_interrupt"
        place_abort_reason = "keyboard_interrupt"
        print("\nCtrl-C：停止采集并尝试安全松扭矩。")
        return 130
    except Exception as exc:
        if not pick_saved:
            pick_abort_reason = f"runtime_error: {exc}"
        place_abort_reason = f"runtime_error: {exc}"
        raise
    finally:
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
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
        if pick_recorder is not None and not pick_saved:
            pick_recorder.abort(pick_abort_reason)
        if place_recorder is not None and not place_saved:
            place_recorder.abort(place_abort_reason)


if __name__ == "__main__":
    raise SystemExit(main())
