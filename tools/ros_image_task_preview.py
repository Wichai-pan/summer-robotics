#!/usr/bin/env python3
"""Relay an existing ROS Image topic without opening the physical camera."""

from __future__ import annotations

import argparse

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

from forestbridge_task_frame_publisher import TaskFramePublisher


def image_to_rgb(message: Image) -> np.ndarray:
    channels_by_encoding = {"rgb8": 3, "bgr8": 3, "rgba8": 4, "bgra8": 4}
    channels = channels_by_encoding.get(message.encoding.lower())
    if channels is None:
        raise ValueError(f"unsupported ROS image encoding: {message.encoding}")
    row = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
    pixels = row[:, : message.width * channels].reshape(
        message.height, message.width, channels
    )
    encoding = message.encoding.lower()
    if encoding == "rgb8":
        return pixels.copy()
    if encoding == "bgr8":
        return pixels[:, :, ::-1].copy()
    if encoding == "rgba8":
        return pixels[:, :, :3].copy()
    return pixels[:, :, [2, 1, 0]].copy()


class ImagePreviewNode(Node):
    def __init__(self, topic: str) -> None:
        super().__init__("forestbridge_task_image_preview")
        self.publisher = TaskFramePublisher(preferred_sources=("gemini",))
        self.publisher.start()
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self.subscription = self.create_subscription(Image, topic, self._image, qos)

    def _image(self, message: Image) -> None:
        try:
            self.publisher.offer("gemini", image_to_rgb(message))
        except ValueError as exc:
            self.get_logger().warning(str(exc))

    def destroy_node(self) -> bool:
        self.publisher.close()
        return super().destroy_node()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="/camera/color/image_raw")
    args = parser.parse_args()
    rclpy.init()
    node = ImagePreviewNode(args.topic)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
