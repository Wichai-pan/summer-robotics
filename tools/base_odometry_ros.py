#!/usr/bin/env python3
"""ROS 2 adapter for wheel odometry; ROS imports occur only in live mode."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import time
import threading


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--publish-tf", action="store_true")
    parser.add_argument("--enable-control", action="store_true")
    parser.add_argument("--confirmed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/slam/sts3215_wheel_feedback_unresolved.json"),
    )
    parser.add_argument("--port")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        if args.publish_tf:
            raise SystemExit("formal fused route reserves odom -> base_link TF for robot_localization")
        from base_odometry_core import BodyVelocity, SE2Odometry
        from base_wheel_feedback import FakeWheelFeedbackSource

        odometry = SE2Odometry()
        result = None
        for sample in FakeWheelFeedbackSource(BodyVelocity(0.1, 0.02, math.radians(5))).samples():
            result = odometry.update(sample)
        assert result is not None
        print(f"PASS ROS-adapter dry-run pose={result[0]}; ROS and hardware were not imported")
        return 0
    if not args.live:
        raise SystemExit("select --dry-run; live is entered only by the locked fused-SLAM session")

    # Live implementation remains behind the verified-unit gate. Importing this file is hardware-free.
    if args.publish_tf:
        raise SystemExit("robot_localization exclusively owns odom -> base_link TF")
    if args.enable_control and not args.confirmed:
        raise SystemExit("live control requires the locked launcher confirmation")

    from base_keyboard import THETA_SPEED, WHEEL_IDS, XY_SPEED, body_to_wheel_raw
    from base_odometry_core import FeedbackFault, FeedbackLimits, SE2Odometry
    from base_wheel_feedback import STS3215WheelFeedbackSource, load_sts_config
    from portutil import BOARDS, resolve_port

    config = load_sts_config(args.config, require_resolved=True)
    rate_hz = float(config["expected_feedback_hz"])
    if not math.isfinite(rate_hz) or rate_hz <= 0:
        raise SystemExit("expected_feedback_hz must be positive and verified")
    port = resolve_port(BOARDS["white"], override=args.port)

    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry

    def covariance(diagonal: list[float]) -> list[float]:
        output = [0.0] * 36
        for index, value in enumerate(diagonal):
            output[index * 6 + index] = float(value)
        return output

    rclpy.init()
    node = rclpy.create_node("base_wheel_odometry")
    publisher = node.create_publisher(Odometry, "/wheel/odom", 10)
    limits = FeedbackLimits(
        max_gap_s=float(config["max_gap_s"]),
        max_age_s=float(config["max_age_s"]),
        max_wheel_speed_rad_s=float(config["max_wheel_speed_rad_s"]),
        max_wheel_accel_rad_s2=float(config["max_wheel_accel_rad_s2"]),
    )
    odometry = SE2Odometry(limits)
    command_lock = threading.Lock()
    latest_command = {motor_id: 0 for motor_id in WHEEL_IDS}
    latest_command_s = 0.0

    def receive_command(message: Twist) -> None:
        nonlocal latest_command_s
        values = (message.linear.x, message.linear.y, message.angular.z)
        if not all(math.isfinite(value) for value in values):
            node.get_logger().error("rejected non-finite /cmd_vel")
            return
        if (
            abs(message.linear.x) > XY_SPEED
            or abs(message.linear.y) > XY_SPEED
            or abs(message.angular.z) > math.radians(THETA_SPEED)
        ):
            node.get_logger().error("rejected /cmd_vel beyond established base limits")
            return
        raw = body_to_wheel_raw(
            message.linear.x, message.linear.y, math.degrees(message.angular.z)
        )
        with command_lock:
            latest_command.update(dict(zip(WHEEL_IDS, raw)))
            latest_command_s = time.monotonic()

    def command_provider() -> dict[int, int]:
        with command_lock:
            if time.monotonic() - latest_command_s > 0.25:
                return {motor_id: 0 for motor_id in WHEEL_IDS}
            return dict(latest_command)

    if args.enable_control:
        node.create_subscription(Twist, "/cmd_vel", receive_command, 10)
    stop_event = threading.Event()
    source = STS3215WheelFeedbackSource(
        port,
        config,
        rate_hz=rate_hz,
        command_provider=command_provider if args.enable_control else None,
        stop_requested=stop_event.is_set,
    )
    pose_covariance = covariance(config["pose_covariance_diagonal"])
    twist_covariance = covariance(config["twist_covariance_diagonal"])
    ros_anchor_ns = node.get_clock().now().nanoseconds
    monotonic_anchor_s = time.monotonic()
    samples = iter(source.samples())
    try:
        while rclpy.ok():
            sample = next(samples)
            if not rclpy.ok():
                break
            pose, velocity = odometry.update(sample)
            message = Odometry()
            measurement_ns = ros_anchor_ns + int(
                (sample.monotonic_s - monotonic_anchor_s) * 1_000_000_000
            )
            message.header.stamp = rclpy.time.Time(nanoseconds=measurement_ns).to_msg()
            message.header.frame_id = "odom"
            message.child_frame_id = "base_link"
            message.pose.pose.position.x = pose.x_m
            message.pose.pose.position.y = pose.y_m
            message.pose.pose.orientation.z = math.sin(pose.yaw_rad / 2.0)
            message.pose.pose.orientation.w = math.cos(pose.yaw_rad / 2.0)
            message.pose.covariance = pose_covariance
            message.twist.twist.linear.x = velocity.vx_mps
            message.twist.twist.linear.y = velocity.vy_mps
            message.twist.twist.angular.z = velocity.wz_rad_s
            message.twist.covariance = twist_covariance
            publisher.publish(message)
            rclpy.spin_once(node, timeout_sec=0.0)
    except (FeedbackFault, RuntimeError) as exc:
        node.get_logger().fatal(f"wheel feedback fault; owning motion session must stop: {exc}")
        return 1
    finally:
        stop_event.set()
        close = getattr(samples, "close", None)
        if close is not None:
            close()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
