#!/usr/bin/env python3
"""同时预览多个 OpenCV 摄像头，用于给手腕相机做物理编号。

示例（Mac 上两只手腕相机目前为 0、1）：
    conda activate lerobot
    python tools/preview_cameras.py 0 1

按 q 或 Esc 退出。相机索引会因拔插顺序而变化，运行前可先执行
`lerobot-find-cameras opencv --record-time-s 2` 确认。
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np


def open_camera(index: int, width: int | None, height: int | None, fps: float | None) -> cv2.VideoCapture:
    """在 macOS 上明确使用 AVFoundation；其他平台交给 OpenCV 自动选择后端。"""
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    capture = cv2.VideoCapture(index, backend)
    if width is not None:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height is not None:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps is not None:
        capture.set(cv2.CAP_PROP_FPS, fps)
    return capture


def frame_with_label(frame: np.ndarray | None, index: int, target_height: int) -> np.ndarray:
    if frame is None:
        panel = np.zeros((target_height, int(target_height * 16 / 9), 3), dtype=np.uint8)
        cv2.putText(panel, f"Camera {index}: no frame", (24, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return panel

    scale = target_height / frame.shape[0]
    panel = cv2.resize(frame, (round(frame.shape[1] * scale), target_height))
    cv2.rectangle(panel, (0, 0), (panel.shape[1], 36), (0, 0, 0), thickness=-1)
    cv2.putText(
        panel,
        f"Camera {index}  {frame.shape[1]}x{frame.shape[0]}",
        (12, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 0),
        2,
    )
    return panel


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview one or more OpenCV cameras side by side.")
    parser.add_argument("indices", type=int, nargs="*", default=[0, 1], help="OpenCV camera indices (default: 0 1)")
    parser.add_argument("--width", type=int, help="Request capture width, e.g. 1280")
    parser.add_argument("--height", type=int, help="Request capture height, e.g. 720")
    parser.add_argument("--fps", type=float, help="Request capture FPS, e.g. 30")
    parser.add_argument("--display-height", type=int, default=480, help="Per-camera preview height (default: 480)")
    args = parser.parse_args()

    captures = {i: open_camera(i, args.width, args.height, args.fps) for i in args.indices}
    unavailable = [i for i, cap in captures.items() if not cap.isOpened()]
    if unavailable:
        print(f"无法打开相机: {unavailable}。确认 macOS 已允许 Terminal 访问摄像头，并检查索引。")

    print(f"正在预览相机 {args.indices}；按 q 或 Esc 退出。")
    last_report = time.monotonic()
    try:
        while True:
            panels: list[np.ndarray] = []
            status: list[str] = []
            for index, capture in captures.items():
                ok, frame = capture.read() if capture.isOpened() else (False, None)
                panels.append(frame_with_label(frame if ok else None, index, args.display_height))
                status.append(f"{index}:{'ok' if ok else 'failed'}")

            cv2.imshow("Wrist camera preview — q / Esc to exit", cv2.hconcat(panels))
            if time.monotonic() - last_report > 5:
                print("  ".join(status))
                last_report = time.monotonic()
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        for capture in captures.values():
            capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
