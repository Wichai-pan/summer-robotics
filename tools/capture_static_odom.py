#!/usr/bin/env python3
"""Capture RTAB-Map odometry and quality messages as compact JSONL."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument(
        "--warmup",
        type=float,
        default=2.0,
        help="subscribe without recording for this many seconds before capture",
    )
    parser.add_argument("--output", type=Path, default=Path("static-odom.jsonl"))
    parser.add_argument(
        "--ready-file",
        type=Path,
        help="create this file exactly when the post-warmup recording window begins",
    )
    parser.add_argument("--odom-topic", default="/rtabmap/odom")
    parser.add_argument("--info-topic", default="/rtabmap/odom_info")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print subscriptions without importing ROS or opening hardware",
    )
    return parser.parse_args()


class StreamGate:
    """Keep startup samples out of the measured recording window."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._recording = False

    def observe(self, stream: str) -> bool:
        self._seen.add(stream)
        return self._recording

    def start_recording(self) -> None:
        missing = {"odom", "odom_info"} - self._seen
        if missing:
            raise RuntimeError(f"warmup missing streams: {', '.join(sorted(missing))}")
        self._recording = True


def stamp_seconds(stamp: object) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0


def run_live(args: argparse.Namespace) -> int:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rtabmap_msgs.msg import OdomInfo

    args.output.parent.mkdir(parents=True, exist_ok=True)
    handle = args.output.open("w", encoding="utf-8", buffering=1)
    gate = StreamGate()

    class StaticOdomRecorder(Node):
        def __init__(self) -> None:
            super().__init__("static_odom_recorder")
            self.odom_count = 0
            self.info_count = 0
            self.create_subscription(Odometry, args.odom_topic, self.record_odom, 100)
            self.create_subscription(OdomInfo, args.info_topic, self.record_info, 100)

        def write(self, record: dict) -> None:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

        def record_odom(self, message: object) -> None:
            if not gate.observe("odom"):
                return
            position = message.pose.pose.position
            orientation = message.pose.pose.orientation
            self.write(
                {
                    "type": "odom",
                    "stamp_s": stamp_seconds(message.header.stamp),
                    "receive_monotonic_s": time.monotonic(),
                    "frame_id": message.header.frame_id,
                    "child_frame_id": message.child_frame_id,
                    "position": [position.x, position.y, position.z],
                    "orientation": [
                        orientation.x,
                        orientation.y,
                        orientation.z,
                        orientation.w,
                    ],
                }
            )
            self.odom_count += 1

        def record_info(self, message: object) -> None:
            if not gate.observe("odom_info"):
                return
            self.write(
                {
                    "type": "odom_info",
                    "stamp_s": stamp_seconds(message.header.stamp),
                    "receive_monotonic_s": time.monotonic(),
                    "lost": bool(message.lost),
                    "matches": int(message.matches),
                    "inliers": int(message.inliers),
                    "features": int(message.features),
                    "time_estimation_s": float(message.time_estimation),
                    "interval_s": float(message.interval),
                }
            )
            self.info_count += 1

    rclpy.init()
    node = StaticOdomRecorder()
    try:
        warmup_deadline = time.monotonic() + args.warmup
        while rclpy.ok() and time.monotonic() < warmup_deadline:
            rclpy.spin_once(
                node,
                timeout_sec=min(0.1, max(0.0, warmup_deadline - time.monotonic())),
            )
        gate.start_recording()
        if args.ready_file is not None:
            args.ready_file.parent.mkdir(parents=True, exist_ok=True)
            args.ready_file.write_text(
                json.dumps({"recording_started_monotonic_s": time.monotonic()}) + "\n",
                encoding="utf-8",
            )
        deadline = time.monotonic() + args.duration
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=min(0.1, max(0.0, deadline - time.monotonic())))
    finally:
        odom_count = node.odom_count
        info_count = node.info_count
        node.destroy_node()
        rclpy.shutdown()
        handle.close()

    print(f"Captured odom={odom_count} odom_info={info_count} to {args.output}")
    return 0 if odom_count > 1 and info_count > 1 else 1


def main() -> int:
    args = parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if args.warmup <= 0:
        raise SystemExit("--warmup must be positive")
    if args.dry_run:
        print(
            f"DRY RUN: subscribe odom={args.odom_topic} info={args.info_topic} "
            f"for warmup={args.warmup:.1f}s then duration={args.duration:.1f}s; "
            f"output={args.output}; ROS not imported"
        )
        return 0
    return run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
