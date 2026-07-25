#!/usr/bin/env python3
"""只读读取 Gemini 335 前方深度，输出中心区域的稳健距离统计。

本脚本绝不打开串口、不控制底盘；它是将深度加入导航安全门之前的测量工具。
需要在独立的 ``orbbec-depth`` Conda 环境运行。
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

try:
    from pyorbbecsdk import Config, OBSensorType, Pipeline
except ImportError as exc:
    raise SystemExit(
        "缺少 pyorbbecsdk。请运行：conda activate orbbec-depth"
    ) from exc


MIN_VALID_MM = 200.0
MAX_VALID_MM = 5000.0


def depth_mm(frame) -> np.ndarray:
    """Decode one SDK depth frame into millimetres."""
    raw = np.frombuffer(frame.get_data(), dtype=np.uint16)
    image = raw.reshape((frame.get_height(), frame.get_width())).astype(np.float32)
    return image * float(frame.get_depth_scale())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30, help="有效深度帧数（默认 30）")
    parser.add_argument(
        "--roi-fraction",
        type=float,
        default=0.30,
        help="画面中心正方形 ROI 的边长比例（默认 0.30）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="仅输出一行机器可读的距离统计 JSON（供导航安全门调用）。",
    )
    args = parser.parse_args()
    if args.samples < 1 or not 0.05 <= args.roi_fraction <= 1.0:
        raise SystemExit("--samples 必须 >= 1；--roi-fraction 必须在 0.05 到 1.0。")

    pipeline = Pipeline()
    config = Config()
    try:
        profiles = pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
        config.enable_stream(profiles.get_default_video_stream_profile())
        pipeline.start(config)
    except Exception as exc:
        raise SystemExit(f"无法启动 Gemini Depth 流：{exc}") from exc

    center_values: list[float] = []
    roi_values: list[np.ndarray] = []
    try:
        attempts = 0
        max_attempts = args.samples * 4
        while len(roi_values) < args.samples and attempts < max_attempts:
            attempts += 1
            frames = pipeline.wait_for_frames(1000)
            if frames is None:
                continue
            frame = frames.get_depth_frame()
            if frame is None:
                continue

            mm = depth_mm(frame)
            height, width = mm.shape
            half = max(1, int(min(height, width) * args.roi_fraction / 2))
            cy, cx = height // 2, width // 2
            roi = mm[max(0, cy - half) : min(height, cy + half), max(0, cx - half) : min(width, cx + half)]
            valid = roi[(roi >= MIN_VALID_MM) & (roi <= MAX_VALID_MM)]
            center = float(mm[cy, cx])
            if MIN_VALID_MM <= center <= MAX_VALID_MM:
                center_values.append(center)
            if valid.size:
                roi_values.append(valid)
    finally:
        pipeline.stop()

    if not roi_values:
        raise SystemExit("未读到有效深度值。检查 Gemini USB 3 连接、权限与目标距离。")

    values = np.concatenate(roi_values)
    statistics = {
        "valid_frames": len(roi_values),
        "requested_samples": args.samples,
        "center_median_m": round(float(np.median(center_values) / 1000.0), 3)
        if center_values
        else None,
        "roi_p10_m": round(float(np.percentile(values, 10) / 1000.0), 3),
        "roi_median_m": round(float(np.median(values) / 1000.0), 3),
        "roi_p90_m": round(float(np.percentile(values, 90) / 1000.0), 3),
    }
    if args.json:
        print(json.dumps(statistics, ensure_ascii=False))
        return 0

    print(f"有效帧：{statistics['valid_frames']}/{statistics['requested_samples']}")
    if statistics["center_median_m"] is None:
        print("中心点中位数：无有效值")
    else:
        print(f"中心点中位数：{statistics['center_median_m']:.3f} m")
    print(f"中心 ROI 近端 P10：{statistics['roi_p10_m']:.3f} m")
    print(f"中心 ROI 中位数：{statistics['roi_median_m']:.3f} m")
    print(f"中心 ROI 远端 P90：{statistics['roi_p90_m']:.3f} m")
    print("说明：这是相机光轴中心的几何距离，不等于已检测人物的精确距离；尚未接入电机控制。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
