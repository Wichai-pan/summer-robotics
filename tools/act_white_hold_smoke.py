#!/usr/bin/env python3
"""Hold the white arm at its measured pose for a few seconds.

This is the first torque-enabled ACT deployment gate, but it does not load ACT
and does not execute a policy action. Position-joint goals are seeded from the
same raw encoder sample before torque is enabled. The cyclic wrist remains in
velocity mode with a zero velocity target so the 4095/0 wrap cannot create a
long-path position command.
"""

from __future__ import annotations

import argparse
import json
import math
import time


POSITION_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "gripper",
)
WRIST = "wrist_roll"


def hold_violations(
    start: dict[str, float],
    current: dict[str, float],
    wrist_delta_deg: float,
    arm_limit_deg: float,
    gripper_limit: float,
    wrist_limit_deg: float,
) -> dict[str, float]:
    """Return signed drift values that exceed the hold gate."""
    violations = {}
    for joint in POSITION_JOINTS:
        drift = current[joint] - start[joint]
        limit = gripper_limit if joint == "gripper" else arm_limit_deg
        if abs(drift) > limit:
            violations[joint] = drift
    if abs(wrist_delta_deg) > wrist_limit_deg:
        violations[WRIST] = wrist_delta_deg
    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--white-port")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--folded-pose-json",
        default="/data/act/config/white_folded_pose_v1.json",
    )
    parser.add_argument("--duration-s", type=float, default=3.0)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--max-arm-drift-deg", type=float, default=2.0)
    parser.add_argument("--max-gripper-drift", type=float, default=5.0)
    parser.add_argument("--max-wrist-drift-deg", type=float, default=2.0)
    parser.add_argument("--folded-tolerance-deg", type=float, default=8.0)
    parser.add_argument("--folded-gripper-tolerance", type=float, default=10.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="required to enable torque; without it the script exits before torque",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    positive = (
        args.duration_s,
        args.fps,
        args.max_arm_drift_deg,
        args.max_gripper_drift,
        args.max_wrist_drift_deg,
        args.folded_tolerance_deg,
        args.folded_gripper_tolerance,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("duration, rates and tolerances must be positive")

    from pathlib import Path

    from act_checkpoint_dry_run import (
        positions_from_single_raw_sync,
        wait_for_stable_wrist_raw,
    )
    from black_leads_white_wrap_safe import (
        configure_white_torque_free,
        folded_pose_violations,
        load_folded_pose,
        positions,
        raw_wrist,
        seed_position_goals_from_feedback,
        wrapped_tick_delta,
    )
    from portutil import BOARDS, PortResolutionError, resolve_port

    folded_path = Path(args.folded_pose_json)
    if not folded_path.is_file():
        raise SystemExit(f"folded-pose reference not found: {folded_path}")
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
        print(f"白臂保持测试端口：{port}")
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.white_id}")

        folded_reference, folded_wrist_raw = load_folded_pose(folded_path)
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
        if int(robot.bus.read("Goal_Velocity", WRIST, normalize=False)) != 0:
            raise RuntimeError("wrist goal velocity is not zero before torque")

        print("固定起点校验通过；位置目标已由同一时刻的 raw feedback 初始化。")
        print(json.dumps({"start_state": start_state, "start_raw": start_raw}, indent=2))
        if not args.execute:
            print("DRY RUN：未启用扭矩。添加 --execute 才进行 3 秒保持测试。")
            return 0

        robot.bus.enable_torque(list(POSITION_JOINTS))
        torque_enabled = True
        robot.bus.enable_torque(WRIST)
        started = time.monotonic()
        period = 1.0 / args.fps
        maximum_drift = {joint: 0.0 for joint in (*POSITION_JOINTS, WRIST)}
        samples = 0
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            current_state, current_raw = positions_from_single_raw_sync(robot)
            wrist_delta_deg = (
                wrapped_tick_delta(current_raw[WRIST] % 4096, start_wrist_raw)
                * 360.0
                / 4096.0
            )
            for joint in POSITION_JOINTS:
                drift = abs(current_state[joint] - start_state[joint])
                maximum_drift[joint] = max(maximum_drift[joint], drift)
            maximum_drift[WRIST] = max(maximum_drift[WRIST], abs(wrist_delta_deg))
            violations = hold_violations(
                start_state,
                current_state,
                wrist_delta_deg,
                args.max_arm_drift_deg,
                args.max_gripper_drift,
                args.max_wrist_drift_deg,
            )
            if violations:
                detail = ", ".join(
                    f"{joint}={drift:+.2f}" for joint, drift in violations.items()
                )
                raise RuntimeError(f"hold drift limit exceeded: {detail}")
            samples += 1
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        print(
            json.dumps(
                {
                    "status": "PASS",
                    "duration_s": args.duration_s,
                    "samples": samples,
                    "policy_action_executed": False,
                    "maximum_absolute_drift": maximum_drift,
                },
                indent=2,
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
                    torque_enabled = False
                robot.bus.write("Operating_Mode", WRIST, OperatingMode.POSITION.value)
            finally:
                robot.bus.disconnect(disable_torque=False)
            print("白腕已发送零速度；白臂已松开全部扭矩并恢复位置模式。")


if __name__ == "__main__":
    raise SystemExit(main())
