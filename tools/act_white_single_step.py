#!/usr/bin/env python3
"""Execute exactly one fresh, guarded ACT action on the white arm.

The policy is never loaded here.  This executor consumes an atomically written
plan from ``act_checkpoint_dry_run.py``, re-reads the torque-free arm state,
rejects a stale or mismatched plan, asks for ``MOVE``, performs one bounded
position update, and releases torque.  The cyclic wrist remains in velocity
mode, so encoder wrap cannot turn into a long position move.
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
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--white-port")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--folded-pose-json",
        type=Path,
        default=Path("/data/act/config/white_folded_pose_v1.json"),
    )
    parser.add_argument("--max-plan-age-s", type=float, default=120.0)
    parser.add_argument("--max-state-drift-deg", type=float, default=2.0)
    parser.add_argument("--max-state-gripper-drift", type=float, default=4.0)
    parser.add_argument("--max-state-wrist-drift-deg", type=float, default=2.0)
    parser.add_argument("--max-arm-step-deg", type=float, default=1.0)
    parser.add_argument("--max-gripper-step", type=float, default=2.0)
    parser.add_argument("--max-wrist-speed-deg-s", type=float, default=1.0)
    parser.add_argument("--duration-s", type=float, default=1.0)
    parser.add_argument("--fps", type=float, default=20.0)
    return parser.parse_args()


def bounded_position_targets(
    current: dict[str, float],
    requested: dict[str, float],
    arm_step: float,
    gripper_step: float,
) -> dict[str, float]:
    result = {}
    for joint in POSITION_JOINTS:
        key = f"{joint}.pos"
        step = gripper_step if joint == "gripper" else arm_step
        delta = max(-step, min(step, float(requested[key]) - current[joint]))
        result[joint] = current[joint] + delta
    return result


def plan_state_violations(
    planned: dict[str, float],
    current: dict[str, float],
    wrist_delta_deg: float,
    arm_limit: float,
    gripper_limit: float,
    wrist_limit: float,
) -> dict[str, float]:
    violations = {}
    for joint in POSITION_JOINTS:
        error = current[joint] - float(planned[f"{joint}.pos"])
        limit = gripper_limit if joint == "gripper" else arm_limit
        if abs(error) > limit:
            violations[joint] = error
    if abs(wrist_delta_deg) > wrist_limit:
        violations[WRIST] = wrist_delta_deg
    return violations


def load_plan(path: Path, max_age_s: float) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "forestbridge_act_guarded_step/v1":
        raise RuntimeError(f"unsupported ACT step plan schema: {path}")
    age = time.time() - float(payload["created_unix_s"])
    if age < -5.0 or age > max_age_s:
        raise RuntimeError(f"ACT step plan is stale (age={age:.1f}s, limit={max_age_s:.1f}s)")
    return payload


def main() -> int:
    args = parse_args()
    positive = (
        args.max_plan_age_s,
        args.max_state_drift_deg,
        args.max_state_gripper_drift,
        args.max_state_wrist_drift_deg,
        args.max_arm_step_deg,
        args.max_gripper_step,
        args.max_wrist_speed_deg_s,
        args.duration_s,
        args.fps,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("all limits, durations and rates must be positive")
    if not sys.stdin.isatty():
        raise SystemExit("interactive TTY required; use jetson_robot_exec.sh --interactive")
    if not args.plan.is_file():
        raise SystemExit(f"ACT step plan not found: {args.plan}")
    plan = load_plan(args.plan, args.max_plan_age_s)
    if plan.get("robot_id") != args.white_id:
        raise SystemExit(
            f"plan robot_id={plan.get('robot_id')!r}, executor uses {args.white_id!r}"
        )
    requested = plan["guarded_action"]
    planned_state = plan["live_state"]
    if not isinstance(requested, dict) or not isinstance(planned_state, dict):
        raise SystemExit("ACT step plan has invalid state/action objects")

    from act_checkpoint_dry_run import (
        positions_from_single_raw_sync,
        wait_for_stable_wrist_raw,
    )
    from black_leads_white_wrap_safe import (
        DEG_PER_TICK,
        WRIST as SHARED_WRIST,
        configure_white_torque_free,
        seed_position_goals_from_feedback,
        wrapped_tick_delta,
    )
    from portutil import BOARDS, PortResolutionError, resolve_port
    from wrist_roll_velocity_follow import velocity_command_raw

    assert SHARED_WRIST == WRIST
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
    try:
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.white_id}")

        configure_white_torque_free(robot)
        wrist_velocity_mode = True
        wait_for_stable_wrist_raw(robot.bus)
        seed_position_goals_from_feedback(robot)
        current, current_raw = positions_from_single_raw_sync(robot)
        planned_wrist_raw = int(plan["recorder_branch_wrist_raw"])
        wrist_state_delta = (
            wrapped_tick_delta(current_raw[WRIST] % 4096, planned_wrist_raw)
            * DEG_PER_TICK
        )
        violations = plan_state_violations(
            planned_state,
            current,
            wrist_state_delta,
            args.max_state_drift_deg,
            args.max_state_gripper_drift,
            args.max_state_wrist_drift_deg,
        )
        if violations:
            detail = ", ".join(
                f"{joint}={error:+.2f}" for joint, error in violations.items()
            )
            raise RuntimeError(f"robot moved since ACT plan was generated: {detail}")

        targets = bounded_position_targets(
            current,
            requested,
            args.max_arm_step_deg,
            args.max_gripper_step,
        )
        requested_wrist_speed = float(requested["wrist_roll.vel_deg_s"])
        wrist_speed = max(
            -args.max_wrist_speed_deg_s,
            min(args.max_wrist_speed_deg_s, requested_wrist_speed),
        )
        wrist_velocity_raw = velocity_command_raw(
            wrist_speed,
            gain=1.0,
            maximum_deg_s=args.max_wrist_speed_deg_s,
            deadband_deg=0.01,
        )
        table = {
            joint: {
                "current": current[joint],
                "target": targets[joint],
                "delta": targets[joint] - current[joint],
            }
            for joint in POSITION_JOINTS
        }
        table[WRIST] = {
            "current": current[WRIST],
            "velocity_deg_s": wrist_speed,
            "velocity_raw": wrist_velocity_raw,
        }
        print("ACT 单步计划已重新核对；尚未启用扭矩。")
        print(json.dumps(table, indent=2, ensure_ascii=False))
        print(
            f"只执行一次，持续 {args.duration_s:.1f}s；普通关节≤"
            f"{args.max_arm_step_deg:.1f}°，夹爪≤{args.max_gripper_step:.1f}，"
            f"腕转速度≤{args.max_wrist_speed_deg_s:.1f}°/s，随后立即松扭矩。"
        )
        if input("清空白臂周围并保持可立即断开 12V；输入 MOVE 执行：").strip() != "MOVE":
            print("已取消；没有启用扭矩或发送动作。")
            return 0

        robot.bus.enable_torque(list(POSITION_JOINTS))
        torque_enabled = True
        robot.bus.enable_torque(WRIST)
        robot.bus.sync_write("Goal_Position", targets)
        robot.bus.write("Goal_Velocity", WRIST, wrist_velocity_raw, normalize=False)
        started = time.monotonic()
        start_wrist_raw = current_raw[WRIST] % 4096
        period = 1.0 / args.fps
        last_state = current
        last_raw = current_raw
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            last_state, last_raw = positions_from_single_raw_sync(robot)
            for joint in POSITION_JOINTS:
                allowed = args.max_gripper_step if joint == "gripper" else args.max_arm_step_deg
                if abs(last_state[joint] - current[joint]) > allowed + 1.0:
                    raise RuntimeError(f"{joint} exceeded single-step safety margin")
            wrist_travel = (
                wrapped_tick_delta(last_raw[WRIST] % 4096, start_wrist_raw)
                * DEG_PER_TICK
            )
            if abs(wrist_travel) > args.max_wrist_speed_deg_s * args.duration_s + 1.0:
                raise RuntimeError("wrist_roll exceeded single-step travel safety margin")
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        robot.bus.write("Goal_Velocity", WRIST, 0, normalize=False, num_retry=3)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "policy_steps_executed": 1,
                    "start_state": current,
                    "target": targets,
                    "final_state_before_release": last_state,
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
                robot.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            finally:
                robot.bus.disconnect(disable_torque=False)
            print("白腕已发送零速度；白臂已松开全部扭矩并恢复位置模式。")


if __name__ == "__main__":
    raise SystemExit(main())
