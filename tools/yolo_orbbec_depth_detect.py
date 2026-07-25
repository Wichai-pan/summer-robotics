#!/usr/bin/env python3
"""Detection-only YOLO viewer with robust depth inside aligned object boxes.

Starts an Orbbec SDK sidecar, runs YOLO in the ``lerobot`` environment, and
draws class, confidence, box-centre median/P10 depth. It never imports serial
packages or sends a motor command. Press Q or ESC to stop.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "agents" / "llm_navigation" / "runtime"
DEFAULT_DEPTH_PYTHON = Path.home() / "miniconda3" / "envs" / "orbbec-depth" / "bin" / "python"
MIN_VALID_M, MAX_VALID_M = 0.20, 5.0


@dataclass
class TargetCandidate:
    confidence: float
    box: tuple[int, int, int, int]
    distance_m: float

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0


class TargetLock:
    """Small deterministic association layer for one requested object class."""

    def __init__(self, max_jump_px: float, lost_frames: int, smoothing: float):
        self.max_jump_px = max_jump_px
        self.lost_frames_limit = lost_frames
        self.smoothing = smoothing
        self.candidate: TargetCandidate | None = None
        self.smoothed_distance_m: float | None = None
        self.missing_frames = 0

    def update(self, candidates: list[TargetCandidate]) -> tuple[TargetCandidate | None, str]:
        if self.candidate is None:
            if not candidates:
                return None, "SEARCHING"
            self.candidate = max(candidates, key=lambda item: item.confidence)
            self.smoothed_distance_m = self.candidate.distance_m
            self.missing_frames = 0
            return self.candidate, "ACQUIRED"

        previous_x, previous_y = self.candidate.center
        nearest = min(
            candidates,
            key=lambda item: math.hypot(item.center[0] - previous_x, item.center[1] - previous_y),
            default=None,
        )
        if nearest is not None:
            jump = math.hypot(nearest.center[0] - previous_x, nearest.center[1] - previous_y)
            if jump <= self.max_jump_px:
                self.candidate = nearest
                assert self.smoothed_distance_m is not None
                self.smoothed_distance_m = (
                    self.smoothing * nearest.distance_m + (1.0 - self.smoothing) * self.smoothed_distance_m
                )
                self.missing_frames = 0
                return nearest, "TRACKING"

        self.missing_frames += 1
        if self.missing_frames > self.lost_frames_limit:
            self.candidate = None
            self.smoothed_distance_m = None
            return None, "TARGET_LOST"
        return self.candidate, f"HOLDING({self.missing_frames}/{self.lost_frames_limit})"


def box_depth_statistics(depth_m: np.ndarray, xyxy: tuple[int, int, int, int]) -> tuple[float, float, int] | None:
    """Return a centre-patch target distance plus a conservative near-depth cue.

    The primary distance is the median from a small patch around the exact box
    centre, which is much less contaminated by background than a whole-box
    median. ``near_p10`` remains the P10 of the central 50% and is shown only
    as a conservative warning that some part of the detected object is closer.
    """
    x1, y1, x2, y2 = xyxy
    width, height = x2 - x1, y2 - y1
    if width < 4 or height < 4:
        return None
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    radius = max(4, min(16, min(width, height) // 10))
    centre_patch = depth_m[
        max(0, cy - radius) : min(depth_m.shape[0], cy + radius + 1),
        max(0, cx - radius) : min(depth_m.shape[1], cx + radius + 1),
    ]
    centre_valid = centre_patch[(centre_patch >= MIN_VALID_M) & (centre_patch <= MAX_VALID_M)]
    if centre_valid.size < 20:
        return None
    margin_x, margin_y = int(width * 0.25), int(height * 0.25)
    inner = depth_m[y1 + margin_y : y2 - margin_y, x1 + margin_x : x2 - margin_x]
    valid = inner[(inner >= MIN_VALID_M) & (inner <= MAX_VALID_M)]
    if valid.size < 20:
        return None
    return float(np.median(centre_valid)), float(np.percentile(valid, 10)), int(centre_valid.size)


def target_action(
    image_width: int,
    xyxy: tuple[int, int, int, int],
    distance_m: float,
    standoff_m: float,
    tolerance_m: float,
    horizontal_fov_deg: float,
    turn_threshold_deg: float,
) -> tuple[str, float]:
    """Choose a dry-run local action from target bearing and centre distance."""
    x1, _y1, x2, _y2 = xyxy
    target_x = (x1 + x2) / 2.0
    focal_px = image_width / (2.0 * math.tan(math.radians(horizontal_fov_deg) / 2.0))
    bearing_deg = math.degrees(math.atan2(target_x - image_width / 2.0, focal_px))
    if abs(bearing_deg) > turn_threshold_deg:
        return ("TURN_LEFT" if bearing_deg < 0 else "TURN_RIGHT"), bearing_deg
    if distance_m > standoff_m + tolerance_m:
        return "FORWARD", bearing_deg
    if distance_m < standoff_m - tolerance_m:
        return "TOO_CLOSE_STOP", bearing_deg
    return "ARRIVED", bearing_deg


def start_sidecar(args: argparse.Namespace) -> subprocess.Popen[str]:
    depth_python = Path(args.depth_python).expanduser()
    if not depth_python.is_file():
        raise SystemExit(f"找不到 Orbbec Python：{depth_python}")
    command = [
        str(depth_python),
        str(REPO_ROOT / "tools" / "orbbec_rgbd_aligned_stream.py"),
        "--rgb-output", str(args.rgb_path),
        "--depth-output", str(args.depth_path),
        "--metadata-output", str(args.metadata_path),
        "--max-hz", str(args.sdk_hz),
    ]
    if args.depth_sudo:
        command = ["sudo", "-E", *command]
    print("启动 Orbbec 对齐 RGB-D 流（只检测，不控制机器人）…")
    return subprocess.Popen(command, stdout=None, stderr=None, text=True)


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics YOLO 权重或本地路径")
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--classes", nargs="*", default=None, help="可选：仅显示类别名，例如 bottle person")
    parser.add_argument("--target", help="可选：指定一个接近目标类别，例如 cup 或 bottle")
    parser.add_argument("--standoff-m", type=float, default=0.50, help="目标接近检查点，米（默认 0.50）")
    parser.add_argument("--distance-tolerance-m", type=float, default=0.05, help="到达判断距离容差，米（默认 0.05）")
    parser.add_argument("--turn-threshold-deg", type=float, default=5.0, help="超过此水平偏角先转向（默认 5°）")
    parser.add_argument("--camera-hfov-deg", type=float, default=90.0, help="头部 RGB 水平视场角近似值（默认 90°）")
    parser.add_argument("--dry-run-approach", action="store_true", help="显示指定目标的本地接近决策；绝不控制电机")
    parser.add_argument("--lock-max-jump-px", type=float, default=180.0, help="同一目标相邻帧最大中心跳变像素（默认 180）")
    parser.add_argument("--lock-lost-frames", type=int, default=8, help="连续丢失多少帧后确认目标丢失（默认 8）")
    parser.add_argument("--lock-smoothing", type=float, default=0.35, help="目标距离 EMA 新值权重（默认 0.35）")
    parser.add_argument("--sdk-hz", type=float, default=10.0)
    parser.add_argument("--depth-python", default=str(DEFAULT_DEPTH_PYTHON))
    parser.add_argument("--depth-sudo", action="store_true")
    parser.add_argument("--rgb-path", type=Path, default=RUNTIME_DIR / "orbbec_aligned_rgb.jpg")
    parser.add_argument("--depth-path", type=Path, default=RUNTIME_DIR / "orbbec_aligned_depth.npy")
    parser.add_argument("--metadata-path", type=Path, default=RUNTIME_DIR / "orbbec_aligned_metadata.json")
    args = parser.parse_args()
    if not 0 < args.confidence <= 1 or args.sdk_hz <= 0:
        raise SystemExit("--confidence 必须在 (0, 1]；--sdk-hz 必须为正数。")
    if args.standoff_m <= 0 or args.distance_tolerance_m <= 0 or not 1 <= args.camera_hfov_deg < 180:
        raise SystemExit("--standoff-m、--distance-tolerance-m 必须为正数；--camera-hfov-deg 必须在 1–180。")
    if args.dry_run_approach and not args.target:
        raise SystemExit("--dry-run-approach 需要同时指定 --target，例如 --target cup。")
    if args.lock_max_jump_px <= 0 or args.lock_lost_frames < 0 or not 0 < args.lock_smoothing <= 1:
        raise SystemExit("目标锁参数无效。")
    for path in (args.rgb_path, args.depth_path, args.metadata_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    process = None
    try:
        process = start_sidecar(args)
        print("加载 YOLO 模型…首次运行若本地没有权重，Ultralytics 可能下载 yolo11n.pt。")
        model = YOLO(args.model)
        allowed = set(args.classes) if args.classes else None
        target_lock = TargetLock(args.lock_max_jump_px, args.lock_lost_frames, args.lock_smoothing)
        last_sequence = -1
        window = "YOLO + aligned Orbbec depth  |  Q / ESC to quit"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Orbbec RGB-D sidecar 已退出（状态 {process.returncode}）。")
            try:
                metadata = json.loads(args.metadata_path.read_text(encoding="utf-8"))
                sequence = int(metadata["sequence"])
            except (OSError, ValueError, KeyError):
                time.sleep(0.05)
                continue
            if sequence == last_sequence:
                if cv2.waitKey(1) in (ord("q"), ord("Q"), 27):
                    break
                time.sleep(0.01)
                continue
            image = cv2.imread(str(args.rgb_path), cv2.IMREAD_COLOR)
            try:
                depth_m = np.load(args.depth_path, allow_pickle=False)
            except (OSError, ValueError):
                continue
            if image is None or depth_m.shape[:2] != image.shape[:2]:
                continue
            canvas = image.copy()
            result = model(image, conf=args.confidence, verbose=False)[0]
            names = result.names
            target_candidates: list[TargetCandidate] = []
            for box in result.boxes:
                class_id = int(box.cls.item())
                label = str(names[class_id])
                if allowed and label not in allowed:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].round().int().tolist()
                x1, x2 = max(0, x1), min(image.shape[1], x2)
                y1, y2 = max(0, y1), min(image.shape[0], y2)
                statistics = box_depth_statistics(depth_m, (x1, y1, x2, y2))
                confidence = float(box.conf.item())
                text = f"{label} {confidence:.2f}"
                if statistics:
                    centre_m, near_p10_m, count = statistics
                    text += f"  center={centre_m:.2f}m near={near_p10_m:.2f} ({count})"
                    if label == args.target:
                        target_candidates.append(TargetCandidate(confidence, (x1, y1, x2, y2), centre_m))
                else:
                    text += "  depth=invalid"
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(canvas, text, (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 0), 2)
            cv2.putText(canvas, f"aligned RGB-D sequence {sequence}", (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            if args.dry_run_approach:
                target, lock_state = target_lock.update(target_candidates)
                if target is None:
                    plan_text = f"DRY RUN target={args.target}: {lock_state} -> STOP"
                else:
                    assert target_lock.smoothed_distance_m is not None
                    action, bearing = target_action(
                        image.shape[1],
                        target.box,
                        target_lock.smoothed_distance_m,
                        args.standoff_m,
                        args.distance_tolerance_m,
                        args.camera_hfov_deg,
                        args.turn_threshold_deg,
                    )
                    plan_text = (
                        f"DRY RUN target={args.target} {lock_state}: {action} "
                        f"bearing={bearing:+.1f}deg distance={target_lock.smoothed_distance_m:.2f}m goal={args.standoff_m:.2f}m"
                    )
                    x1, y1, x2, y2 = target.box
                    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 165, 255), 3)
                cv2.putText(canvas, plan_text, (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 165, 255), 2)
            cv2.imshow(window, canvas)
            last_sequence = sequence
            if cv2.waitKey(1) in (ord("q"), ord("Q"), 27):
                break
    finally:
        cv2.destroyAllWindows()
        stop_process(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
