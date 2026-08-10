#!/usr/bin/env python3
"""Read and save one torque-free white-arm folded-pose reference.

This utility never enables torque and never sends a goal position.  The saved
reference is used by the ACT recorder to reject episodes whose start or end
pose differs from the fixed folded pose.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from black_leads_white_wrap_safe import ALL_JOINTS, positions, raw_wrist
from portutil import BOARDS, PortResolutionError, resolve_port


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="override the stable white-board port")
    parser.add_argument("--robot-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/data/act/config/white_folded_pose_v1.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        port = resolve_port(BOARDS["white"], override=args.port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    robot = SO100Follower(
        SO100FollowerConfig(port=port, id=args.robot_id, disable_torque_on_disconnect=True)
    )
    connected = False
    try:
        robot.bus.connect()
        connected = True
        robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(f"white motor registers do not match {args.robot_id}")
        pose = positions(robot.get_observation())
        wrist_raw = raw_wrist(robot.bus)
        print("白臂保持松扭矩；不会发送任何目标位置。")
        print("当前收拢姿态：")
        for joint in ALL_JOINTS:
            print(f"  {joint:<14} {pose[joint]:+8.2f}")
        print(f"  {'wrist_raw':<14} {wrist_raw:8d}")
        if input("确认这是以后每个 episode 的固定起点/终点？输入 SAVE：").strip() != "SAVE":
            print("已取消；没有写文件。")
            return 0
        payload = {
            "schema": "forestbridge_white_folded_pose/v1",
            "robot_id": args.robot_id,
            "board_serial": BOARDS["white"],
            "pose": pose,
            "wrist_raw_diagnostic": wrist_raw,
            "created_unix_s": time.time(),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"已保存固定收拢姿态：{args.output}")
        return 0
    finally:
        if connected:
            try:
                robot.bus.disable_torque(num_retry=3)
            finally:
                robot.bus.disconnect(disable_torque=False)


if __name__ == "__main__":
    raise SystemExit(main())
