#!/usr/bin/env python3
"""Supervised low-speed return of the white arm to its saved folded pose.

Position joints follow a bounded joint-space ramp.  The cyclic wrist computes
the shortest physical delta while still in position mode, then realizes only
that relative delta with a velocity loop.  This avoids commanding a long path
across the 0/4095 encoder wrap.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path


POSITION_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "gripper",
)
WRIST = "wrist_roll"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--white-port")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--folded-pose-json",
        type=Path,
        default=Path("/data/act/config/white_folded_pose_v1.json"),
    )
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--max-arm-speed-deg-s", type=float, default=8.0)
    parser.add_argument("--max-gripper-speed-s", type=float, default=20.0)
    parser.add_argument("--max-wrist-speed-deg-s", type=float, default=4.0)
    parser.add_argument("--wrist-gain-per-s", type=float, default=1.5)
    parser.add_argument("--wrist-deadband-deg", type=float, default=0.5)
    parser.add_argument("--max-wrist-travel-deg", type=float, default=45.0)
    parser.add_argument("--tracking-error-deg", type=float, default=5.0)
    parser.add_argument("--tracking-error-gripper", type=float, default=10.0)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--final-arm-tolerance-deg", type=float, default=2.0)
    parser.add_argument("--final-gripper-tolerance", type=float, default=3.0)
    parser.add_argument("--final-wrist-tolerance-deg", type=float, default=2.0)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def slew_return_positions(
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


def return_errors(
    current: dict[str, float],
    target: dict[str, float],
    wrist_error_deg: float,
) -> dict[str, float]:
    errors = {joint: target[joint] - current[joint] for joint in POSITION_JOINTS}
    errors[WRIST] = wrist_error_deg
    return errors


def within_final_tolerance(
    errors: dict[str, float],
    arm_tolerance: float,
    gripper_tolerance: float,
    wrist_tolerance: float,
) -> bool:
    for joint, error in errors.items():
        tolerance = (
            gripper_tolerance
            if joint == "gripper"
            else wrist_tolerance
            if joint == WRIST
            else arm_tolerance
        )
        if abs(error) > tolerance:
            return False
    return True


def main() -> int:
    args = parse_args()
    positive = (
        args.fps,
        args.max_arm_speed_deg_s,
        args.max_gripper_speed_s,
        args.max_wrist_speed_deg_s,
        args.wrist_gain_per_s,
        args.wrist_deadband_deg,
        args.max_wrist_travel_deg,
        args.tracking_error_deg,
        args.tracking_error_gripper,
        args.timeout_s,
        args.final_arm_tolerance_deg,
        args.final_gripper_tolerance,
        args.final_wrist_tolerance_deg,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("all rates, limits, tolerances and timeout must be positive")
    if not args.folded_pose_json.is_file():
        raise SystemExit(f"folded-pose reference not found: {args.folded_pose_json}")
    if args.execute and not sys.stdin.isatty():
        raise SystemExit("interactive TTY required for --execute")

    from act_checkpoint_dry_run import (
        positions_from_single_raw_sync,
        wait_for_stable_wrist_raw,
    )
    from black_leads_white_wrap_safe import (
        DEG_PER_TICK,
        configure_white_torque_free,
        load_folded_pose,
        positions,
        raw_wrist,
        seed_position_goals_from_feedback,
        wrapped_tick_delta,
    )
    from portutil import BOARDS, PortResolutionError, resolve_port
    from wrist_roll_velocity_follow import velocity_command_raw

    try:
        port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    from lerobot.motors.feetech import OperatingMode
    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    robot = SO100Follower(
        SO100FollowerConfig(
            port=port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )
    connected = False
    torque_enabled = False
    wrist_velocity_mode = False
    restored_position_mode = False
    try:
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.white_id}")

        folded_pose, folded_wrist_raw = load_folded_pose(args.folded_pose_json)
        position_mode_state = positions(robot.get_observation())
        position_mode_wrist_raw = raw_wrist(robot.bus)
        wrist_target_delta_deg = (
            wrapped_tick_delta(folded_wrist_raw, position_mode_wrist_raw)
            * DEG_PER_TICK
        )
        if abs(wrist_target_delta_deg) > args.max_wrist_travel_deg:
            raise RuntimeError(
                f"shortest wrist return is {wrist_target_delta_deg:+.1f}°, exceeding "
                f"limit {args.max_wrist_travel_deg:.1f}°; reposition manually first"
            )
        target_positions = {
            joint: float(folded_pose[joint]) for joint in POSITION_JOINTS
        }
        preview = {
            joint: {
                "current": position_mode_state[joint],
                "target": target_positions[joint],
                "delta": target_positions[joint] - position_mode_state[joint],
            }
            for joint in POSITION_JOINTS
        }
        preview[WRIST] = {
            "current_position_mode_raw": position_mode_wrist_raw,
            "target_position_mode_raw": folded_wrist_raw,
            "shortest_delta_deg": wrist_target_delta_deg,
        }
        print("白臂固定起点回归计划；目前仍为松扭矩。")
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        if not args.execute:
            print("DRY RUN：未启用扭矩或发送动作。添加 --execute 才允许回归。")
            return 0
        if input(
            "清空白臂到收拢姿态的完整路径并保持可立即断开12V；输入 RETURN："
        ).strip() != "RETURN":
            print("已取消；没有启用扭矩或发送动作。")
            return 0

        configure_white_torque_free(robot)
        wrist_velocity_mode = True
        wait_for_stable_wrist_raw(robot.bus)
        seed_position_goals_from_feedback(robot)
        start_state, start_raw = positions_from_single_raw_sync(robot)
        start_wrist_velocity_raw = start_raw[WRIST] % 4096
        previous_wrist_raw = start_wrist_velocity_raw
        wrist_travel_ticks = 0
        command = {joint: start_state[joint] for joint in POSITION_JOINTS}

        robot.bus.enable_torque(list(POSITION_JOINTS))
        torque_enabled = True
        robot.bus.enable_torque(WRIST)
        period = 1.0 / args.fps
        arm_step = args.max_arm_speed_deg_s / args.fps
        gripper_step = args.max_gripper_speed_s / args.fps
        started = time.monotonic()
        stable_cycles = 0
        last_print = -1.0
        while time.monotonic() - started < args.timeout_s:
            loop_started = time.monotonic()
            current_state, current_raw = positions_from_single_raw_sync(robot)
            command = slew_return_positions(
                command, target_positions, arm_step, gripper_step
            )
            # Do not let the command get farther from feedback than the tracking
            # envelope even if a joint stalls.
            for joint in POSITION_JOINTS:
                tracking = (
                    args.tracking_error_gripper
                    if joint == "gripper"
                    else args.tracking_error_deg
                )
                command[joint] = max(
                    current_state[joint] - tracking,
                    min(current_state[joint] + tracking, command[joint]),
                )
            robot.bus.sync_write("Goal_Position", command)

            wrist_now = current_raw[WRIST] % 4096
            wrist_step = wrapped_tick_delta(wrist_now, previous_wrist_raw)
            previous_wrist_raw = wrist_now
            if abs(wrist_step * DEG_PER_TICK) > 20.0:
                raise RuntimeError(f"implausible wrist feedback jump: {wrist_step} ticks")
            wrist_travel_ticks += wrist_step
            wrist_travel_deg = wrist_travel_ticks * DEG_PER_TICK
            wrist_error_deg = wrist_target_delta_deg - wrist_travel_deg
            if abs(wrist_travel_deg) > args.max_wrist_travel_deg + 5.0:
                raise RuntimeError("wrist exceeded return travel safety margin")
            wrist_velocity_raw = velocity_command_raw(
                wrist_error_deg,
                args.wrist_gain_per_s,
                args.max_wrist_speed_deg_s,
                args.wrist_deadband_deg,
            )
            robot.bus.write(
                "Goal_Velocity", WRIST, wrist_velocity_raw, normalize=False
            )

            errors = return_errors(current_state, target_positions, wrist_error_deg)
            if within_final_tolerance(
                errors,
                args.final_arm_tolerance_deg,
                args.final_gripper_tolerance,
                args.final_wrist_tolerance_deg,
            ):
                stable_cycles += 1
                if stable_cycles >= 5:
                    break
            else:
                stable_cycles = 0
            elapsed = time.monotonic() - started
            if elapsed - last_print >= 0.5:
                print(
                    "\r"
                    + f"{elapsed:5.1f}s "
                    + " ".join(
                        f"{joint}={errors[joint]:+5.1f}"
                        for joint in POSITION_JOINTS
                    )
                    + f" wrist={wrist_error_deg:+5.1f}°",
                    end="",
                    flush=True,
                )
                last_print = elapsed
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
        else:
            raise RuntimeError(f"folded-pose return timed out after {args.timeout_s:.1f}s")

        print("\n回归控制达到容差；正在停止并用 position-mode raw 复核。")
        robot.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
        robot.bus.disable_torque(num_retry=3)
        torque_enabled = False
        robot.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
        wrist_velocity_mode = False
        restored_position_mode = True
        time.sleep(0.1)
        final_state = positions(robot.get_observation())
        final_wrist_raw = raw_wrist(robot.bus)
        final_wrist_error = (
            wrapped_tick_delta(final_wrist_raw, folded_wrist_raw) * DEG_PER_TICK
        )
        final_errors = return_errors(
            final_state, target_positions, -final_wrist_error
        )
        if not within_final_tolerance(
            final_errors,
            args.final_arm_tolerance_deg,
            args.final_gripper_tolerance,
            args.final_wrist_tolerance_deg,
        ):
            raise RuntimeError(f"position-mode folded-pose verification failed: {final_errors}")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "final_state": final_state,
                    "final_wrist_raw": final_wrist_raw,
                    "target_wrist_raw": folded_wrist_raw,
                    "final_errors": final_errors,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        if connected:
            try:
                if wrist_velocity_mode:
                    robot.bus.write(
                        "Goal_Velocity", WRIST, 0, normalize=False, num_retry=3
                    )
                if torque_enabled:
                    robot.bus.disable_torque(num_retry=3)
                if not restored_position_mode:
                    robot.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            finally:
                robot.bus.disconnect(disable_torque=False)
            print("白腕已发送零速度；白臂已松开全部扭矩并恢复位置模式。")


if __name__ == "__main__":
    raise SystemExit(main())
