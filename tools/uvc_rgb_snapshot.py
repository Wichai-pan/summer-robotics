#!/usr/bin/env python3
"""Capture one read-only RGB frame from a mapped UVC wrist camera."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-frames", type=int, default=8)
    parser.add_argument("--jpeg-quality", type=int, default=70)
    args = parser.parse_args()
    if args.warmup_frames < 1 or not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("invalid warmup frame count or JPEG quality")

    camera = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not camera.isOpened():
        raise SystemExit(f"无法打开腕部摄像头：{args.device}")
    image = None
    try:
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        for _ in range(max(30, args.warmup_frames * 4)):
            ok, frame = camera.read()
            if ok and frame is not None:
                image = frame
                args.warmup_frames -= 1
                if args.warmup_frames <= 0:
                    break
    finally:
        camera.release()
    if image is None:
        raise SystemExit(f"未读到腕部摄像头画面：{args.device}")
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
    if not ok:
        raise SystemExit("无法编码腕部摄像头 JPEG")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_bytes(encoded.tobytes())
    temporary.replace(args.output)
    print(f"Saved wrist RGB frame: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
