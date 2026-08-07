#!/usr/bin/env python3
"""Record a stable RGB-D point for the blue calibration marker.

This owns only the Gemini 335 RGB-D stream.  It does not calculate IK, open a
motor port, or command a robot, so it can be used for markers held at any safe
calibration pose rather than only at a graspable table position.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

try:
    import pyorbbecsdk as ob
except ImportError as exc:
    raise SystemExit("缺少 pyorbbecsdk；请用 orbbec-depth 环境运行。") from exc


def color_to_bgr(frame) -> np.ndarray | None:
    width, height = frame.get_width(), frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = frame.get_format()
    if fmt == ob.OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if fmt == ob.OBFormat.RGB:
        return cv2.cvtColor(data.reshape((height, width, 3)), cv2.COLOR_RGB2BGR)
    if fmt == ob.OBFormat.BGR:
        return data.reshape((height, width, 3))
    if fmt in (ob.OBFormat.YUYV, ob.OBFormat.YUY2):
        return cv2.cvtColor(data.reshape((height, width, 2)), cv2.COLOR_YUV2BGR_YUY2)
    return None


def blue_mask(
    image: np.ndarray,
    roi: tuple[int, int, int, int] | None,
    min_area: int,
    selected_xy: tuple[int, int] | None,
) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((90, 70, 35), np.uint8), np.array((140, 255, 255), np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    if roi is not None:
        x, y, width, height = roi
        keep = np.zeros_like(mask)
        keep[max(0, y):min(mask.shape[0], y + height), max(0, x):min(mask.shape[1], x + width)] = 255
        mask = cv2.bitwise_and(mask, keep)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return np.zeros_like(mask)
    candidates = [
        component for component in range(1, count)
        if int(stats[component, cv2.CC_STAT_AREA]) >= min_area
    ]
    if not candidates:
        return np.zeros_like(mask)
    if selected_xy is None:
        # Legacy fallback for a tabletop object. For a small marker on the
        # gripper, use --select so a large blue reflection cannot win.
        component = max(candidates, key=lambda item: int(stats[item, cv2.CC_STAT_AREA]))
    else:
        x, y = selected_xy
        if 0 <= x < mask.shape[1] and 0 <= y < mask.shape[0] and labels[y, x] in candidates:
            component = int(labels[y, x])
        else:
            # A click may land on a small gap in the coloured surface; choose
            # the closest valid component only when it is genuinely nearby.
            distances = []
            for candidate in candidates:
                cx = float(stats[candidate, cv2.CC_STAT_LEFT] + stats[candidate, cv2.CC_STAT_WIDTH] / 2)
                cy = float(stats[candidate, cv2.CC_STAT_TOP] + stats[candidate, cv2.CC_STAT_HEIGHT] / 2)
                distances.append(((cx - x) ** 2 + (cy - y) ** 2, candidate))
            distance_sq, component = min(distances)
            if distance_sq > 45.0**2:
                return np.zeros_like(mask)
    if stats[component, cv2.CC_STAT_AREA] < min_area:
        return np.zeros_like(mask)
    return np.where(labels == component, 255, 0).astype(np.uint8)


def point_from_frame(bgr: np.ndarray, depth_m: np.ndarray, intr, roi, min_area: int, selected_xy):
    mask = blue_mask(bgr, roi, min_area, selected_xy)
    valid = (mask > 0) & np.isfinite(depth_m) & (depth_m >= 0.10) & (depth_m <= 1.50)
    rows, cols = np.nonzero(valid)
    if len(rows) < 30:
        return None, mask
    z = depth_m[rows, cols]
    median_z = float(np.median(z))
    mad = float(np.median(np.abs(z - median_z)))
    keep = np.abs(z - median_z) <= max(0.008, 5.0 * mad)
    rows, cols, z = rows[keep], cols[keep], z[keep]
    if len(rows) < 30:
        return None, mask
    xyz = np.column_stack(((cols - intr.cx) * z / intr.fx, (rows - intr.cy) * z / intr.fy, z))
    bbox = cv2.boundingRect(np.column_stack((cols, rows)).astype(np.int32))
    return {
        "camera_xyz_m": np.median(xyz, axis=0).astype(float).tolist(),
        "depth_mad_m": mad,
        "pixels": int(len(rows)),
        "bbox_xywh": [int(v) for v in bbox],
    }, mask


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--min-area", type=int, default=80, help="minimum visible blue area in pixels (default: 80)")
    parser.add_argument(
        "--select", action="store_true",
        help="click the actual blue marker once in the preview; required when it is not the largest blue region",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON result path")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if args.samples < 3 or args.min_area < 30:
        raise SystemExit("--samples 至少为 3，--min-area 至少为 30。")
    pipeline, started = ob.Pipeline(), False
    try:
        config = ob.Config()
        colors = pipeline.get_stream_profile_list(ob.OBSensorType.COLOR_SENSOR)
        depths = pipeline.get_stream_profile_list(ob.OBSensorType.DEPTH_SENSOR)
        config.enable_stream(colors.get_default_video_stream_profile())
        config.enable_stream(depths.get_default_video_stream_profile())
        if hasattr(ob, "OBFrameAggregateOutputMode"):
            config.set_frame_aggregate_output_mode(ob.OBFrameAggregateOutputMode.FULL_FRAME_REQUIRE)
        try:
            pipeline.enable_frame_sync()
        except Exception:
            pass
        align = ob.AlignFilter(align_to_stream=ob.OBStreamType.COLOR_STREAM)
        pipeline.start(config)
        started = True
        params = pipeline.get_camera_param()
        intr = params.rgb_intrinsic
        samples: list[np.ndarray] = []
        last = None
        clicked: list[tuple[int, int] | None] = [None]
        window_name = "blue marker | click marker once | ESC abort"
        if args.select:
            cv2.namedWindow(window_name)
            cv2.setMouseCallback(
                window_name,
                lambda event, x, y, _flags, _param: clicked.__setitem__(0, (x, y))
                if event == cv2.EVENT_LBUTTONDOWN else None,
            )
        deadline = time.monotonic() + 30.0
        while len(samples) < args.samples and time.monotonic() < deadline:
            frames = pipeline.wait_for_frames(1000)
            if not frames:
                continue
            aligned = align.process(frames)
            if not aligned:
                continue
            color, depth_frame = aligned.get_color_frame(), aligned.get_depth_frame()
            if color is None or depth_frame is None:
                continue
            bgr = color_to_bgr(color)
            if bgr is None:
                continue
            raw = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
            depth_m = raw.reshape((depth_frame.get_height(), depth_frame.get_width())).astype(np.float32)
            depth_m *= float(depth_frame.get_depth_scale()) / 1000.0
            depth_m[raw.reshape(depth_m.shape) == 0] = np.nan
            if depth_m.shape != bgr.shape[:2]:
                continue
            if args.select and clicked[0] is None:
                view = bgr.copy()
                cv2.putText(view, "Click the blue marker once", (20, 36), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, (0, 255, 255), 2, cv2.LINE_AA)
                cv2.imshow(window_name, view)
                if cv2.waitKey(1) == 27:
                    raise KeyboardInterrupt
                continue
            result, mask = point_from_frame(
                bgr, depth_m, intr, tuple(args.roi) if args.roi else None, args.min_area, clicked[0]
            )
            if result is None:
                continue
            samples.append(result["camera_xyz_m"])
            last = result
            if args.preview:
                view = bgr.copy()
                x, y, w, h = result["bbox_xywh"]
                cv2.rectangle(view, (x, y), (x + w, y + h), (0, 255, 0), 2)
                if clicked[0] is not None:
                    cv2.drawMarker(view, clicked[0], (0, 255, 255), cv2.MARKER_CROSS, 18, 2)
                cv2.imshow(window_name, view)
                if cv2.waitKey(1) == 27:
                    raise KeyboardInterrupt
        if len(samples) < args.samples:
            raise SystemExit(f"30 秒内只采到 {len(samples)}/{args.samples} 个有效标记帧。")
        points = np.stack(samples)
        median = np.median(points, axis=0)
        spread = float(np.max(np.linalg.norm(points - median, axis=1)))
        if spread > 0.012:
            raise SystemExit(f"标记不稳定：最大散布 {spread:.4f} m > 0.0120 m。")
        output = {
            "schema": "gemini_blue_marker/v1",
            "coordinate_frame": "color_camera_optical_frame (+x right, +y down, +z forward)",
            "marker_camera_xyz_m": median.tolist(),
            "max_spread_m": spread,
            "samples": len(samples),
            "roi_xywh": args.roi,
            "last_frame": last,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(output, indent=2))
        return 0
    finally:
        if started:
            pipeline.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
