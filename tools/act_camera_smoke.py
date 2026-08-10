#!/usr/bin/env python3
"""No-motor Gemini + wrist RGB freshness/identity smoke test for ACT."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from act_episode_recorder import GeminiRGBSource, OpenCVRGBSource


def save_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError(f"JPEG encode failed: {path}")
    path.write_bytes(encoded.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--white-wrist-device", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--sample-fps", type=float, default=20.0)
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--max-age-s", type=float, default=0.25)
    args = parser.parse_args()
    if min(args.width, args.height, args.camera_fps, args.samples) <= 0 or args.sample_fps <= 0:
        raise SystemExit("dimensions, FPS and samples must be positive")

    gemini = GeminiRGBSource(args.width, args.height, args.camera_fps)
    wrist = OpenCVRGBSource(args.white_wrist_device, args.width, args.height, args.camera_fps)
    sequences = {"gemini_rgb": [], "white_wrist_rgb": []}
    ages = {"gemini_rgb": [], "white_wrist_rgb": []}
    first = None
    last = None
    try:
        gemini.start()
        wrist.start()
        period = 1.0 / args.sample_fps
        for index in range(args.samples):
            started = time.monotonic()
            now = time.monotonic()
            gemini_sample = gemini.latest(args.max_age_s)
            wrist_sample = wrist.latest(args.max_age_s)
            sequences["gemini_rgb"].append(gemini_sample.sequence)
            sequences["white_wrist_rgb"].append(wrist_sample.sequence)
            ages["gemini_rgb"].append(now - gemini_sample.monotonic_s)
            ages["white_wrist_rgb"].append(now - wrist_sample.monotonic_s)
            pair = (gemini_sample.rgb.copy(), wrist_sample.rgb.copy())
            if first is None:
                first = pair
            last = pair
            sleep_s = period - (time.monotonic() - started)
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        gemini.close()
        wrist.close()

    assert first is not None and last is not None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    save_rgb(args.output_dir / "gemini_first.jpg", first[0])
    save_rgb(args.output_dir / "wrist_first.jpg", first[1])
    save_rgb(args.output_dir / "gemini_last.jpg", last[0])
    save_rgb(args.output_dir / "wrist_last.jpg", last[1])
    result = {
        "schema": "forestbridge_act_camera_smoke/v1",
        "requested": {
            "width": args.width,
            "height": args.height,
            "camera_fps": args.camera_fps,
            "sample_fps": args.sample_fps,
            "samples": args.samples,
        },
        "identities": {"gemini_rgb": gemini.identity, "white_wrist_rgb": wrist.identity},
        "streams": {
            name: {
                "unique_sequences": len(set(values)),
                "duplicate_samples": len(values) - len(set(values)),
                "max_age_s": max(ages[name]),
                "monotonic_sequence": all(b >= a for a, b in zip(values, values[1:], strict=False)),
            }
            for name, values in sequences.items()
        },
        "color_order": "RGB",
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "camera_smoke.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if any(not stream["monotonic_sequence"] for stream in result["streams"].values()):
        raise RuntimeError("camera sequence moved backwards")
    if any(stream["unique_sequences"] < args.samples // 2 for stream in result["streams"].values()):
        raise RuntimeError("camera produced too many duplicate sampled frames")
    print("PASS camera identity/freshness smoke; inspect the saved wrist JPEG physically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
