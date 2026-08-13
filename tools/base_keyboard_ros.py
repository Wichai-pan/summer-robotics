#!/usr/bin/env python3
"""Publish the established SSH WASD/QE base commands as ROS ``/cmd_vel``."""

from __future__ import annotations

import argparse
import math
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--deadman-ms", type=float, default=250.0)
    parser.add_argument("--xy-speed-mps", type=float, default=0.04)
    parser.add_argument("--theta-speed-deg-s", type=float, default=12.0)
    parser.add_argument("--max-runtime-s", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (
        args.deadman_ms <= 0
        or args.xy_speed_mps <= 0
        or args.theta_speed_deg_s <= 0
        or args.max_runtime_s <= 0
        or args.dry_run == args.live
    ):
        raise SystemExit("select exactly one mode and use a positive deadman")
    from base_keyboard import TerminalInput, command_from_keys

    if args.dry_run:
        print("PASS ROS keyboard dry-run; W/S X, A/D Y, Q/E yaw, Space stop, X/Esc exit")
        return 0

    import rclpy
    from geometry_msgs.msg import Twist

    rclpy.init()
    node = rclpy.create_node("base_keyboard_cmd_vel")
    publisher = node.create_publisher(Twist, "/cmd_vel", 10)
    keys = TerminalInput(args.deadman_ms / 1000.0)
    keys.connect()
    started = time.monotonic()
    try:
        while rclpy.ok() and not keys.should_exit():
            if time.monotonic() - started >= args.max_runtime_s:
                node.get_logger().info("base control time limit reached; stopping")
                break
            vx, vy, yaw_deg_s = command_from_keys(
                keys.pressed(), args.xy_speed_mps, args.theta_speed_deg_s
            )
            message = Twist()
            message.linear.x = vx
            message.linear.y = vy
            message.angular.z = math.radians(yaw_deg_s)
            publisher.publish(message)
            rclpy.spin_once(node, timeout_sec=0.0)
            time.sleep(1.0 / 30.0)
    finally:
        stop = Twist()
        publisher.publish(stop)
        keys.disconnect()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
