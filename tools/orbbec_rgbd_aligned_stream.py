#!/usr/bin/env python3
"""Persist aligned Gemini 335 RGB-D frames for a separate perception process.

The Orbbec SDK stays in the isolated ``orbbec-depth`` environment. Each frame
is software-aligned depth-to-colour, then written atomically as a JPEG, a
float32 depth ``.npy`` array in metres, and JSON metadata. No motor or serial
code exists here.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path

import cv2
import numpy as np

try:
    from pyorbbecsdk import (
        AlignFilter,
        Config,
        OBFormat,
        OBFrameAggregateOutputMode,
        OBSensorType,
        OBStreamType,
        Pipeline,
    )
except ImportError as exc:
    raise SystemExit("缺少 pyorbbecsdk。请运行：conda activate orbbec-depth") from exc


STOP_REQUESTED = False


def request_stop(_signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def color_to_bgr(frame) -> np.ndarray | None:
    width, height = frame.get_width(), frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = frame.get_format()
    if fmt == OBFormat.RGB:
        return cv2.cvtColor(data.reshape((height, width, 3)), cv2.COLOR_RGB2BGR)
    if fmt == OBFormat.BGR:
        return data.reshape((height, width, 3))
    if fmt == OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if fmt in (OBFormat.YUYV, OBFormat.YUY2):
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_YUY2)
    if fmt == OBFormat.UYVY:
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_UYVY)
    return None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def atomic_save_npy(path: Path, array: np.ndarray) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        np.save(handle, array)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rgb-output", type=Path, required=True)
    parser.add_argument("--depth-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    parser.add_argument("--max-hz", type=float, default=10.0)
    parser.add_argument("--jpeg-quality", type=int, default=90)
    args = parser.parse_args()
    if args.max_hz <= 0 or not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("--max-hz 必须为正数；--jpeg-quality 必须在 1–100。")
    for path in (args.rgb_output, args.depth_output, args.metadata_output):
        path.parent.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    pipeline = Pipeline()
    config = Config()
    started = False
    try:
        color_profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        color_profile = color_profiles.get_video_stream_profile(0, 0, OBFormat.RGB, 0)
        depth_profiles = pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
        config.enable_stream(color_profile)
        config.enable_stream(depth_profiles.get_default_video_stream_profile())
        config.set_frame_aggregate_output_mode(OBFrameAggregateOutputMode.FULL_FRAME_REQUIRE)
        align_filter = AlignFilter(align_to_stream=OBStreamType.COLOR_STREAM)
        pipeline.start(config)
        started = True
        sequence = 0
        last_publish = 0.0
        min_interval = 1.0 / args.max_hz
        while not STOP_REQUESTED:
            frames = pipeline.wait_for_frames(500)
            if frames is None:
                continue
            now = time.monotonic()
            if now - last_publish < min_interval:
                continue
            aligned = align_filter.process(frames)
            if aligned is None:
                continue
            color_frame = aligned.get_color_frame()
            depth_frame = aligned.get_depth_frame()
            if color_frame is None or depth_frame is None:
                continue
            color = color_to_bgr(color_frame)
            if color is None:
                continue
            depth = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
            depth = depth.reshape((depth_frame.get_height(), depth_frame.get_width())).astype(np.float32)
            depth *= float(depth_frame.get_depth_scale()) / 1000.0
            # Aligned frames must have a one-to-one pixel correspondence.
            if depth.shape[:2] != color.shape[:2]:
                continue
            encoded_ok, encoded = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            if not encoded_ok:
                continue
            atomic_write_bytes(args.rgb_output, encoded.tobytes())
            atomic_save_npy(args.depth_output, depth)
            metadata = {
                "sequence": sequence,
                "monotonic_s": round(now, 6),
                "rgb_path": str(args.rgb_output.resolve()),
                "depth_path": str(args.depth_output.resolve()),
                "width": int(color.shape[1]),
                "height": int(color.shape[0]),
                "depth_unit": "m",
                "aligned": "depth_to_color_software",
            }
            atomic_write_bytes(args.metadata_output, json.dumps(metadata).encode("utf-8"))
            sequence += 1
            last_publish = now
    finally:
        if started:
            pipeline.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
