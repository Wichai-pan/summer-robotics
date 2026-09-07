#!/usr/bin/env python3
"""Request a Nav2 path without starting any controller or publishing cmd_vel."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal-x", type=float, required=True)
    parser.add_argument("--goal-y", type=float, required=True)
    parser.add_argument("--goal-yaw-deg", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--append-exact-goal", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout_s <= 0 or not all(math.isfinite(value) for value in (args.timeout_s, args.goal_x, args.goal_y, args.goal_yaw_deg)):
        raise SystemExit("goal coordinates and timeout must be finite, with timeout > 0")

    import rclpy
    from nav2_msgs.action import ComputePathToPose
    from rclpy.action import ActionClient
    from lifecycle_msgs.srv import GetState
    from lifecycle_msgs.msg import State
    from action_msgs.msg import GoalStatus

    rclpy.init()
    node = rclpy.create_node("forestbridge_nav2_path_dry_run")
    client = ActionClient(node, ComputePathToPose, "/compute_path_to_pose")
    lifecycle_states = {}
    try:
        # Action discovery alone does not mean a lifecycle action server is active.
        for managed_node in ("map_server", "planner_server"):
            state_client = node.create_client(GetState, f"/{managed_node}/get_state")
            deadline = time.monotonic() + args.timeout_s
            last_state = "unavailable"
            try:
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    if not state_client.wait_for_service(timeout_sec=min(1.0, remaining)):
                        continue
                    future = state_client.call_async(GetState.Request())
                    rclpy.spin_until_future_complete(node, future, timeout_sec=min(1.0, remaining))
                    if future.done() and future.result() is not None:
                        state = future.result().current_state
                        last_state = state.label
                        if state.id == State.PRIMARY_STATE_ACTIVE:
                            lifecycle_states[managed_node] = {"id": int(state.id), "label": state.label}
                            print(f"PASS lifecycle {managed_node}: {state.label} ({state.id})", flush=True)
                            break
                    else:
                        future.cancel()
                    time.sleep(0.2)
                else:
                    raise RuntimeError(
                        f"Nav2 {managed_node} did not become active (last state={last_state}); "
                        "inspect nav2-lifecycle-manager.log; no goal submitted"
                    )
            finally:
                node.destroy_client(state_client)
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
        if wrapped.status != GoalStatus.STATUS_SUCCEEDED:
            raise RuntimeError(f"Nav2 planning failed with action status {wrapped.status}")
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
        planner_endpoint = list(poses_xy_yaw_deg[-1])
        endpoint_offset_m = math.hypot(
            planner_endpoint[0] - args.goal_x, planner_endpoint[1] - args.goal_y
        )
        if args.append_exact_goal and endpoint_offset_m > 1e-6:
            poses_xy_yaw_deg.append([args.goal_x, args.goal_y, args.goal_yaw_deg])
        payload = {
            "status": "PASS",
            "planner": "GridBased",
            "lifecycle_states_before_goal": lifecycle_states,
            "action_status": int(wrapped.status),
            "start_source": "live map->odom->base_link TF",
            "goal_map_xy_yaw_deg": [args.goal_x, args.goal_y, args.goal_yaw_deg],
            "planning_time_s": float(wrapped.result.planning_time.sec) + float(wrapped.result.planning_time.nanosec) / 1_000_000_000.0,
            "poses_map_xyz": [
                [float(item.pose.position.x), float(item.pose.position.y), float(item.pose.position.z)]
                for item in path.poses
            ],
            "poses_map_xy_yaw_deg": poses_xy_yaw_deg,
            "final_path_yaw_deg": poses_xy_yaw_deg[-1][2],
            "planner_endpoint_xy_yaw_deg": planner_endpoint,
            "planner_endpoint_offset_m": endpoint_offset_m,
            "exact_goal_appended": bool(args.append_exact_goal and endpoint_offset_m > 1e-6),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**payload, "poses_map_xyz": f"{len(path.poses)} poses written to {args.output}"}, indent=2))
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
