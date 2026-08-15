#!/usr/bin/env python3
"""Request a Nav2 path without starting any controller or publishing cmd_vel."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal-x", type=float, required=True)
    parser.add_argument("--goal-y", type=float, required=True)
    parser.add_argument("--goal-yaw-deg", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout_s <= 0 or not all(math.isfinite(value) for value in (args.goal_x, args.goal_y, args.goal_yaw_deg)):
        raise SystemExit("goal coordinates and timeout must be finite, with timeout > 0")

    import rclpy
    from nav2_msgs.action import ComputePathToPose
    from rclpy.action import ActionClient

    rclpy.init()
    node = rclpy.create_node("forestbridge_nav2_path_dry_run")
    client = ActionClient(node, ComputePathToPose, "/compute_path_to_pose")
    try:
        if not client.wait_for_server(timeout_sec=args.timeout_s):
            raise RuntimeError("Nav2 ComputePathToPose action did not become available")
        goal = ComputePathToPose.Goal()
        goal.goal.header.frame_id = "map"
        goal.goal.pose.position.x = args.goal_x
        goal.goal.pose.position.y = args.goal_y
        yaw_rad = math.radians(args.goal_yaw_deg)
        goal.goal.pose.orientation.z = math.sin(yaw_rad / 2.0)
        goal.goal.pose.orientation.w = math.cos(yaw_rad / 2.0)
        goal.use_start = False
        goal.planner_id = "GridBased"
        send_future = client.send_goal_async(goal)
        rclpy.spin_until_future_complete(node, send_future, timeout_sec=args.timeout_s)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError("Nav2 rejected the planning-only goal")
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(node, result_future, timeout_sec=args.timeout_s)
        wrapped = result_future.result()
        if wrapped is None:
            raise RuntimeError("Nav2 path request timed out")
        path = wrapped.result.path
        if len(path.poses) < 2:
            raise RuntimeError("Nav2 returned an empty or degenerate path")
        poses_xy_yaw_deg = []
        for item in path.poses:
            orientation = item.pose.orientation
            yaw = math.degrees(
                math.atan2(
                    2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
                    1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
                )
            )
            poses_xy_yaw_deg.append(
                [float(item.pose.position.x), float(item.pose.position.y), float(yaw)]
            )
        payload = {
            "status": "PASS",
            "planner": "GridBased",
            "start_source": "live map->odom->base_link TF",
            "goal_map_xy_yaw_deg": [args.goal_x, args.goal_y, args.goal_yaw_deg],
            "planning_time_s": float(wrapped.result.planning_time.sec) + float(wrapped.result.planning_time.nanosec) / 1_000_000_000.0,
            "poses_map_xyz": [
                [float(item.pose.position.x), float(item.pose.position.y), float(item.pose.position.z)]
                for item in path.poses
            ],
            "poses_map_xy_yaw_deg": poses_xy_yaw_deg,
            "final_path_yaw_deg": poses_xy_yaw_deg[-1][2],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**payload, "poses_map_xyz": f"{len(path.poses)} poses written to {args.output}"}, indent=2))
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
