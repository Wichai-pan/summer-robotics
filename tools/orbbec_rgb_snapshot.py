#!/usr/bin/env python3
"""Capture one read-only Gemini RGB frame without requiring a depth stream."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

try:
    from pyorbbecsdk import Config, OBFormat, OBSensorType, Pipeline
except ImportError as exc:
    raise SystemExit("缺少 pyorbbecsdk") from exc


def decode(frame) -> np.ndarray | None:
    width, height = frame.get_width(), frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = frame.get_format()
    if fmt == OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if fmt == OBFormat.RGB:
        return cv2.cvtColor(data.reshape((height, width, 3)), cv2.COLOR_RGB2BGR)
    if fmt == OBFormat.BGR:
        return data.reshape((height, width, 3))
    if fmt in (OBFormat.YUYV, OBFormat.YUY2):
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_YUY2)
    if fmt == OBFormat.UYVY:
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_UYVY)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-frames", type=int, default=8)
    parser.add_argument("--jpeg-quality", type=int, default=70)
    args = parser.parse_args()
    if args.warmup_frames < 1 or not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("invalid warmup frame count or JPEG quality")

    pipeline = Pipeline()
    config = Config()
    started = False
    image = None
    try:
        profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        config.enable_stream(profiles.get_default_video_stream_profile())
        pipeline.start(config)
        started = True
        decoded_frames = 0
        for _ in range(max(30, args.warmup_frames * 4)):
            frames = pipeline.wait_for_frames(1000)
            if frames is None:
                continue
            frame = frames.get_color_frame()
            if frame is None:
                continue
            decoded = decode(frame)
            if decoded is None:
                continue
            decoded_frames += 1
            image = decoded
            if decoded_frames >= args.warmup_frames:
                break
    finally:
        if started:
            pipeline.stop()

    if image is None:
        raise SystemExit("未读到有效 Gemini RGB 帧")
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
    if not ok:
        raise SystemExit("无法编码 Gemini RGB JPEG")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_bytes(encoded.tobytes())
    temporary.replace(args.output)
    print(f"Saved Gemini RGB frame: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
