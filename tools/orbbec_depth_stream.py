#!/usr/bin/env python3
"""Publish Gemini 335 forward depth statistics as newline-delimited JSON.

This program owns one persistent official Orbbec SDK depth pipeline. It does
not open serial ports, command motors, or make navigation decisions; a local
controller may consume its stdout and fail closed if this stream stalls.
Run it from the isolated ``orbbec-depth`` environment.
"""

from __future__ import annotations

import argparse
import json
import signal
import time

import numpy as np

try:
    from pyorbbecsdk import Config, OBSensorType, Pipeline
except ImportError as exc:
    raise SystemExit("缺少 pyorbbecsdk。请运行：conda activate orbbec-depth") from exc


MIN_VALID_MM = 200.0
MAX_VALID_MM = 5000.0
STOP_REQUESTED = False


def request_stop(_signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roi-fraction", type=float, default=0.30, help="中心正方形 ROI 边长比例（默认 0.30）")
    parser.add_argument("--max-hz", type=float, default=15.0, help="最多发布多少条统计/秒（默认 15）")
    args = parser.parse_args()
    if not 0.05 <= args.roi_fraction <= 1.0 or args.max_hz <= 0:
        raise SystemExit("--roi-fraction 必须在 0.05 到 1.0；--max-hz 必须为正数。")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    pipeline = Pipeline()
    config = Config()
    started = False
    try:
        profiles = pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
        config.enable_stream(profiles.get_default_video_stream_profile())
        pipeline.start(config)
        started = True
        min_interval = 1.0 / args.max_hz
        last_publish = 0.0
        sequence = 0
        while not STOP_REQUESTED:
            frames = pipeline.wait_for_frames(500)
            if frames is None:
                continue
            frame = frames.get_depth_frame()
            if frame is None:
                continue
            now = time.monotonic()
            if now - last_publish < min_interval:
                continue
            depth = np.frombuffer(frame.get_data(), dtype=np.uint16)
            depth = depth.reshape((frame.get_height(), frame.get_width())).astype(np.float32)
            depth *= float(frame.get_depth_scale())
            height, width = depth.shape
            half = max(1, int(min(height, width) * args.roi_fraction / 2))
            cy, cx = height // 2, width // 2
            roi = depth[max(0, cy - half) : min(height, cy + half), max(0, cx - half) : min(width, cx + half)]
            values = roi[(roi >= MIN_VALID_MM) & (roi <= MAX_VALID_MM)]
            if not values.size:
                continue
            center = float(depth[cy, cx])
            payload = {
                "sequence": sequence,
                "monotonic_s": round(now, 6),
                "roi_p10_m": round(float(np.percentile(values, 10) / 1000.0), 3),
                "roi_median_m": round(float(np.median(values) / 1000.0), 3),
                "center_m": round(center / 1000.0, 3) if MIN_VALID_MM <= center <= MAX_VALID_MM else None,
            }
            print(json.dumps(payload), flush=True)
            sequence += 1
            last_publish = now
    finally:
        if started:
            pipeline.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
