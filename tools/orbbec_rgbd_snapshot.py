#!/usr/bin/env python3
"""Capture one Gemini 335 RGB-D snapshot through the official Orbbec SDK.

The script intentionally owns *both* the colour and depth streams in one SDK
pipeline. It is a building block for LLM navigation on macOS, where OpenCV and
the SDK cannot reliably alternate ownership of the same Gemini UVC device.
It never opens a serial port or commands a motor.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

try:
    from pyorbbecsdk import Config, OBFormat, OBSensorType, Pipeline
except ImportError as exc:
    raise SystemExit("缺少 pyorbbecsdk。请运行：conda activate orbbec-depth") from exc


MIN_VALID_MM = 200.0
MAX_VALID_MM = 5000.0


def color_to_bgr(frame) -> np.ndarray | None:
    """Decode common Gemini colour profiles into an OpenCV BGR image."""
    width, height = frame.get_width(), frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = frame.get_format()
    if fmt == OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if fmt == OBFormat.RGB:
        rgb = data.reshape((height, width, 3))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if fmt == OBFormat.BGR:
        return data.reshape((height, width, 3))
    if fmt in (OBFormat.YUYV, OBFormat.YUY2):
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_YUY2)
    if fmt == OBFormat.UYVY:
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_UYVY)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=15, help="有效 RGB-D 帧数（默认 15）")
    parser.add_argument("--roi-fraction", type=float, default=0.30, help="中心正方形 ROI 边长比例")
    parser.add_argument("--output", type=Path, required=True, help="输出 JPEG 的绝对或相对路径")
    parser.add_argument("--metadata", type=Path, help="可选：将同一份统计 JSON 写入此路径")
    parser.add_argument("--jpeg-quality", type=int, default=90, help="JPEG 质量，1–100（默认 90）")
    parser.add_argument("--json", action="store_true", help="输出一行机器可读统计 JSON")
    args = parser.parse_args()
    if args.samples < 1 or not 0.05 <= args.roi_fraction <= 1.0 or not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("--samples、--roi-fraction 或 --jpeg-quality 参数无效。")

    pipeline = Pipeline()
    config = Config()
    started = False
    try:
        color_profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        depth_profiles = pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
        config.enable_stream(color_profiles.get_default_video_stream_profile())
        config.enable_stream(depth_profiles.get_default_video_stream_profile())
        pipeline.start(config)
        started = True
    except Exception as exc:
        raise SystemExit(f"无法启动 Gemini RGB-D 流：{exc}") from exc

    roi_values: list[np.ndarray] = []
    center_values: list[float] = []
    color_image: np.ndarray | None = None
    color_format = "unknown"
    try:
        attempts = 0
        max_attempts = args.samples * 5
        while len(roi_values) < args.samples and attempts < max_attempts:
            attempts += 1
            frames = pipeline.wait_for_frames(1000)
            if frames is None:
                continue
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if color_frame is None or depth_frame is None:
                continue
            decoded = color_to_bgr(color_frame)
            if decoded is None:
                color_format = str(color_frame.get_format())
                continue

            depth = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
            depth = depth.reshape((depth_frame.get_height(), depth_frame.get_width())).astype(np.float32)
            depth *= float(depth_frame.get_depth_scale())
            height, width = depth.shape
            half = max(1, int(min(height, width) * args.roi_fraction / 2))
            cy, cx = height // 2, width // 2
            roi = depth[max(0, cy - half) : min(height, cy + half), max(0, cx - half) : min(width, cx + half)]
            valid = roi[(roi >= MIN_VALID_MM) & (roi <= MAX_VALID_MM)]
            if not valid.size:
                continue
            center = float(depth[cy, cx])
            if MIN_VALID_MM <= center <= MAX_VALID_MM:
                center_values.append(center)
            roi_values.append(valid)
            color_image = decoded
            color_format = str(color_frame.get_format())
    finally:
        if started:
            pipeline.stop()

    if color_image is None or not roi_values:
        raise SystemExit(f"未读到有效 RGB-D 帧（最后颜色格式：{color_format}）。")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", color_image, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
    if not ok:
        raise SystemExit("无法编码 Gemini RGB JPEG。")
    args.output.write_bytes(encoded.tobytes())

    values = np.concatenate(roi_values)
    result = {
        "image_path": str(args.output.resolve()),
        "valid_frames": len(roi_values),
        "requested_samples": args.samples,
        "color_format": color_format,
        "center_median_m": round(float(np.median(center_values) / 1000.0), 3) if center_values else None,
        "roi_p10_m": round(float(np.percentile(values, 10) / 1000.0), 3),
        "roi_median_m": round(float(np.median(values) / 1000.0), 3),
        "roi_p90_m": round(float(np.percentile(values, 90) / 1000.0), 3),
    }
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"已保存 RGB：{result['image_path']}")
        print(f"有效 RGB-D 帧：{result['valid_frames']}/{result['requested_samples']}")
        print(f"中心 ROI 近端 P10：{result['roi_p10_m']:.3f} m")
        print(f"中心 ROI 中位数：{result['roi_median_m']:.3f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
