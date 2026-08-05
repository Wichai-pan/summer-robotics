"""Live Gemini 335 blue-cylinder centroid test with diagnostics and recording."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from gemini335 import Gemini335Camera
from perception import DetectorConfig, annotate, detect_blue_cylinder


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "outputs")
    parser.add_argument("--min-depth", type=float, default=0.10, help="metres")
    parser.add_argument("--max-depth", type=float, default=3.0, help="metres")
    parser.add_argument("--min-area", type=int, default=250, help="blue component pixels")
    parser.add_argument("--radius", type=float, default=0.018, help="known cylinder radius in metres")
    parser.add_argument("--hue-low", type=int, default=90, help="OpenCV HSV hue [0,179]")
    parser.add_argument("--hue-high", type=int, default=140)
    parser.add_argument("--smooth-frames", type=int, default=5)
    parser.add_argument("--print-every", type=float, default=0.5, help="console interval in seconds")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0, help="0 means unlimited")
    parser.add_argument("--reference-distance", type=float, default=None,
                        help="optional known optical-axis distance (m) for depth error report")
    return parser.parse_args()


def depth_colormap(depth_m: np.ndarray, min_depth: float, max_depth: float) -> np.ndarray:
    scaled = np.nan_to_num((depth_m - min_depth) / max(max_depth - min_depth, 1e-6), nan=0.0)
    image = np.clip(255.0 * (1.0 - scaled), 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(image, cv2.COLORMAP_TURBO)
    colored[~np.isfinite(depth_m)] = 0
    return colored


def save_snapshot(directory: Path, index: int, bgr, depth_m, mask, annotated, detection):
    stem = f"frame_{index:06d}"
    cv2.imwrite(str(directory / f"{stem}_rgb.png"), bgr)
    cv2.imwrite(str(directory / f"{stem}_mask.png"), mask)
    cv2.imwrite(str(directory / f"{stem}_annotated.png"), annotated)
    np.save(directory / f"{stem}_depth_m.npy", depth_m)
    payload = None if detection is None else detection.to_dict()
    (directory / f"{stem}_measurement.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(f"[SAVE] {directory / stem}_[rgb|mask|annotated|depth_m|measurement]")


def main() -> int:
    args = parse_args()
    session = args.output_dir.resolve() / datetime.now().strftime("%Y%m%d_%H%M%S")
    session.mkdir(parents=True, exist_ok=True)
    cfg = DetectorConfig(
        hsv_lower=(args.hue_low, 70, 35),
        hsv_upper=(args.hue_high, 255, 255),
        min_area_px=args.min_area,
        min_depth_m=args.min_depth,
        max_depth_m=args.max_depth,
        cylinder_radius_m=args.radius,
    )
    camera = Gemini335Camera()
    intr = camera.start()
    calibration_path = session / "factory_calibration.json"
    calibration_path.write_text(json.dumps(camera.calibration_dict(), indent=2), encoding="utf-8")
    print(f"[CAMERA] active RGB intrinsics: {intr}")
    print(f"[CALIBRATION] saved {calibration_path}")
    print("[COORDINATES] +x right, +y down, +z forward; metres; RGB optical center origin")
    print("[KEYS] q/ESC quit | s save full diagnostic snapshot | c re-export calibration")

    csv_path = session / "measurements.csv"
    csv_file = csv_path.open("w", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    writer.writerow([
        "time_s", "frame", "detected", "x_m", "y_m", "z_m", "range_m",
        "surface_x_m", "surface_y_m", "surface_z_m", "confidence",
        "depth_mad_m", "valid_depth_pixels",
    ])
    history = deque(maxlen=max(1, args.smooth_frames))
    started = last_frame = last_print = time.perf_counter()
    fps = 0.0
    frame_index = 0
    last_images = None

    try:
        while args.max_frames <= 0 or frame_index < args.max_frames:
            captured = camera.read()
            if captured is None:
                continue
            bgr, depth_m = captured
            detection, mask = detect_blue_cylinder(bgr, depth_m, intr, cfg)
            now = time.perf_counter()
            dt = now - last_frame
            last_frame = now
            if dt > 0:
                fps = (0.90 * fps + 0.10 / dt) if fps else 1.0 / dt

            if detection:
                history.append(np.asarray(detection.cylinder_center_estimate_m))
                smoothed = np.median(np.stack(history), axis=0)
                detection.cylinder_center_estimate_m = tuple(float(v) for v in smoothed)
                detection.range_m = float(np.linalg.norm(smoothed))
                center = detection.cylinder_center_estimate_m
                surface = detection.surface_centroid_m
                writer.writerow([
                    now - started, frame_index, 1, *center, detection.range_m, *surface,
                    detection.confidence, detection.depth_mad_m, detection.valid_depth_pixels,
                ])
            else:
                history.clear()
                writer.writerow([now - started, frame_index, 0, "", "", "", "", "", "", "", "", "", ""])

            annotated = annotate(bgr, mask, detection, intr, fps)
            depth_view = depth_colormap(depth_m, args.min_depth, args.max_depth)
            panel = np.hstack((annotated, depth_view))
            last_images = (bgr, depth_m, mask, annotated, detection)

            if now - last_print >= args.print_every:
                last_print = now
                if detection:
                    c = np.asarray(detection.cylinder_center_estimate_m)
                    message = (
                        f"[DETECTION] xyz_m=[{c[0]:+.4f}, {c[1]:+.4f}, {c[2]:+.4f}] "
                        f"range={detection.range_m:.4f} surface_z={detection.median_depth_m:.4f} "
                        f"MAD={detection.depth_mad_m*1000:.1f}mm conf={detection.confidence:.2f}"
                    )
                    if args.reference_distance is not None:
                        error = c[2] - args.reference_distance
                        message += f" reference_z_error={error*1000:+.1f}mm"
                    print(message)
                else:
                    print("[DETECTION] no valid blue cylinder")
                csv_file.flush()

            key = -1
            if not args.headless:
                cv2.imshow("Gemini 335 | RGB detection + aligned depth | q quit, s save", panel)
                key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s") and last_images:
                save_snapshot(session, frame_index, *last_images)
            if key == ord("c"):
                calibration_path.write_text(json.dumps(camera.calibration_dict(), indent=2), encoding="utf-8")
                print(f"[CALIBRATION] refreshed {calibration_path}")
            frame_index += 1
    except KeyboardInterrupt:
        pass
    finally:
        csv_file.close()
        camera.stop()
        cv2.destroyAllWindows()
    print(f"[DONE] measurements={csv_path}; frames={frame_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
