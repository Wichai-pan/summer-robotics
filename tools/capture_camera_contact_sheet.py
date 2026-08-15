#!/usr/bin/env python3
"""Capture one labeled, read-only contact sheet from Gemini and UVC cameras.

The tool is intended to identify physical camera mounts without guessing from
unstable ``/dev/videoN`` numbers. It sends no serial command and opens no motor
device. Use the Jetson hardware wrapper to expose only Gemini and the requested
UVC device paths.

Example:
    python3 tools/capture_camera_contact_sheet.py \\
      --camera 'UVC USB 2.4.1 | host /dev/video8=/dev/wrist-2-4-1' \\
      --camera 'UVC USB 2.4.3 | host /dev/video4=/dev/wrist-2-4-3' \\
      --output /data/camera-check/contact_sheet.jpg
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class CaptureResult:
    label: str
    device: str
    status: str
    shape_bgr: list[int] | None
    error: str | None


def parse_camera_spec(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("camera must use LABEL=DEVICE syntax")
    label, device = (part.strip() for part in value.split("=", 1))
    if not label or not device:
        raise argparse.ArgumentTypeError("camera label and device must both be non-empty")
    return label, device


def draw_text(image: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int], scale: float = 0.55) -> None:
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def error_panel(width: int, height: int, label: str, device: str, error: str) -> np.ndarray:
    panel = np.zeros((height, width, 3), dtype=np.uint8)
    panel[:] = (25, 25, 25)
    draw_text(panel, label, 16, 42, (0, 80, 255), 0.7)
    draw_text(panel, device, 16, 74, (210, 210, 210), 0.5)
    draw_text(panel, "NO FRAME", 16, height // 2, (0, 0, 255), 0.8)
    draw_text(panel, error[:85], 16, height // 2 + 34, (180, 180, 180), 0.45)
    return panel


def label_panel(frame_bgr: np.ndarray, label: str, device: str, status: str) -> np.ndarray:
    height, width = frame_bgr.shape[:2]
    panel = frame_bgr.copy()
    cv2.rectangle(panel, (0, 0), (width, 78), (0, 0, 0), thickness=-1)
    draw_text(panel, label, 16, 30, (0, 255, 0), 0.65)
    draw_text(panel, device, 16, 56, (235, 235, 235), 0.48)
    draw_text(panel, status, 16, 75, (0, 220, 255), 0.42)
    return panel


def capture_uvc(label: str, device: str, width: int, height: int, fps: int, warmup_frames: int) -> tuple[np.ndarray | None, CaptureResult]:
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    try:
        if not capture.isOpened():
            return None, CaptureResult(label, device, "no_frame", None, "VideoCapture did not open")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
        frame = None
        for _ in range(warmup_frames):
            ok, candidate = capture.read()
            if ok and candidate is not None:
                frame = candidate
        if frame is None:
            return None, CaptureResult(label, device, "no_frame", None, "no valid UVC frame after warm-up")
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        return frame, CaptureResult(label, device, "ok", list(frame.shape), None)
    finally:
        capture.release()


def capture_gemini(width: int, height: int, fps: int) -> tuple[np.ndarray | None, CaptureResult]:
    label = "Gemini 335 RGB-D head"
    device = "Orbbec SDK color stream"
    source = None
    try:
        from act_episode_recorder import GeminiRGBSource

        source = GeminiRGBSource(width, height, fps)
        source.start()
        # The source owns a background thread; allow it a bounded interval to
        # receive the first fresh RGB frame.
        deadline = time.monotonic() + 3.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                sample = source.latest(max_age_s=1.0)
                frame = cv2.cvtColor(sample.rgb, cv2.COLOR_RGB2BGR)
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                return frame, CaptureResult(label, device, "ok", list(frame.shape), None)
            except Exception as exc:  # source may still be warming up
                last_error = exc
                time.sleep(0.05)
        return None, CaptureResult(label, device, "no_frame", None, str(last_error or "Gemini timed out"))
    except Exception as exc:
        return None, CaptureResult(label, device, "no_frame", None, str(exc))
    finally:
        if source is not None:
            source.close()


def compose(panels: list[np.ndarray], title: str) -> np.ndarray:
    gap = 8
    header_height = 50
    body = cv2.hconcat(panels)
    canvas = np.zeros((body.shape[0] + header_height, body.shape[1], 3), dtype=np.uint8)
    canvas[:header_height] = (18, 18, 18)
    canvas[header_height:] = body
    draw_text(canvas, title, 16, 32, (0, 255, 255), 0.72)
    if gap:
        for boundary in range(panels[0].shape[1], body.shape[1], panels[0].shape[1]):
            cv2.rectangle(canvas, (boundary - gap // 2, header_height), (boundary + gap // 2, canvas.shape[0]), (18, 18, 18), -1)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=parse_camera_spec, action="append", default=[], help="UVC camera as LABEL=DEVICE; repeatable")
    parser.add_argument("--without-gemini", action="store_true", help="Do not capture the Gemini RGB stream")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--warmup-frames", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.width, args.height, args.fps, args.warmup_frames) <= 0:
        raise SystemExit("width, height, fps, and warmup frames must be positive")
    if args.without_gemini and not args.camera:
        raise SystemExit("supply at least one --camera when --without-gemini is set")

    captures: list[CaptureResult] = []
    panels: list[np.ndarray] = []
    if not args.without_gemini:
        frame, result = capture_gemini(args.width, args.height, args.fps)
        captures.append(result)
        panels.append(
            label_panel(frame, result.label, result.device, "OK")
            if frame is not None
            else error_panel(args.width, args.height, result.label, result.device, result.error or "unknown error")
        )
    for label, device in args.camera:
        frame, result = capture_uvc(label, device, args.width, args.height, args.fps, args.warmup_frames)
        captures.append(result)
        panels.append(
            label_panel(frame, result.label, result.device, "OK")
            if frame is not None
            else error_panel(args.width, args.height, result.label, result.device, result.error or "unknown error")
        )

    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = compose(panels, "ForestBridge camera contact sheet | read-only, no motor or serial access")
    if not cv2.imwrite(str(output), sheet):
        raise RuntimeError(f"failed to write {output}")
    manifest = {
        "schema": "forestbridge/camera-contact-sheet/v1",
        "hardware_access": {"cameras": True, "serial": False, "motor_command_sent": False},
        "output": str(output),
        "captures": [asdict(result) for result in captures],
    }
    manifest_path = output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    if not any(result.status == "ok" for result in captures):
        raise RuntimeError("no camera delivered a frame")
    print(f"Saved labeled contact sheet: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
