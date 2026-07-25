#!/usr/bin/env python3
"""Supervised, target-specific base approach using local YOLO + Gemini depth.

This is deliberately a local controller: it receives a fixed target class and
standoff distance, then obtains aligned RGB-D, runs YOLO, and proposes exactly
one of the already-tested fixed base actions. By default it is DRY RUN and
never imports a serial package. ``--execute`` remains bounded and requires a
human confirmation before it launches ``base_motion_step.py``, which asks for
MOVE a second time.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from yolo_orbbec_depth_detect import (
    DEFAULT_DEPTH_PYTHON,
    MIN_VALID_M,
    MAX_VALID_M,
    TargetCandidate,
    TargetLock,
    box_depth_statistics,
    start_sidecar,
    stop_process,
    target_action,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "agents" / "llm_navigation" / "runtime"


def read_observation(
    args: argparse.Namespace,
    model: YOLO,
    target_lock: TargetLock,
    last_sequence: int,
) -> tuple[dict[str, object], int]:
    """Wait for one new, internally consistent RGB/depth observation."""
    deadline = time.monotonic() + args.frame_timeout_s
    while time.monotonic() < deadline:
        try:
            first_metadata = json.loads(args.metadata_path.read_text(encoding="utf-8"))
            sequence = int(first_metadata["sequence"])
        except (OSError, ValueError, KeyError):
            time.sleep(0.05)
            continue
        if sequence == last_sequence:
            time.sleep(0.03)
            continue
        image = cv2.imread(str(args.rgb_path), cv2.IMREAD_COLOR)
        try:
            depth_m = np.load(args.depth_path, allow_pickle=False)
            second_sequence = int(json.loads(args.metadata_path.read_text(encoding="utf-8"))["sequence"])
        except (OSError, ValueError, KeyError):
            continue
        # The producer writes metadata last. Rechecking it prevents consuming
        # an RGB image and depth array from different producer updates.
        if second_sequence != sequence or image is None or image.shape[:2] != depth_m.shape[:2]:
            continue

        target_candidates: list[TargetCandidate] = []
        person_visible = False
        result = model(image, conf=args.confidence, verbose=False)[0]
        for box in result.boxes:
            label = str(result.names[int(box.cls.item())])
            if label == "person":
                person_visible = True
            if label != args.target:
                continue
            x1, y1, x2, y2 = box.xyxy[0].round().int().tolist()
            x1, x2 = max(0, x1), min(image.shape[1], x2)
            y1, y2 = max(0, y1), min(image.shape[0], y2)
            statistics = box_depth_statistics(depth_m, (x1, y1, x2, y2))
            if statistics is not None:
                distance_m, _near_p10_m, _count = statistics
                target_candidates.append(TargetCandidate(float(box.conf.item()), (x1, y1, x2, y2), distance_m))

        target, lock_state = target_lock.update(target_candidates)
        h, w = depth_m.shape
        half_h, half_w = max(1, int(h * 0.15)), max(1, int(w * 0.15))
        centre_roi = depth_m[h // 2 - half_h : h // 2 + half_h, w // 2 - half_w : w // 2 + half_w]
        valid = centre_roi[(centre_roi >= MIN_VALID_M) & (centre_roi <= MAX_VALID_M)]
        forward_p10_m = float(np.percentile(valid, 10)) if valid.size >= 20 else None

        observation: dict[str, object] = {
            "sequence": sequence,
            "person_visible": person_visible,
            "lock_state": lock_state,
            "forward_p10_m": forward_p10_m,
            "target": target,
            "image_width": image.shape[1],
        }
        return observation, sequence
    raise TimeoutError(f"在 {args.frame_timeout_s:.1f} 秒内未得到新的对齐 RGB-D 帧。")


def choose_action(args: argparse.Namespace, observation: dict[str, object]) -> tuple[str, str]:
    """Fail closed for invalid depth or target loss, not for a distant operator.

    A person visible elsewhere is common when the operator watches the screen;
    the two explicit MOVE checks, rather than a whole-image person detector,
    decide whether the short path is physically clear. ``person`` still cannot
    be selected as the target class.
    """
    target = observation["target"]
    if target is None:
        return "STOP", f"目标 {args.target!r} 未稳定锁定（{observation['lock_state']}）。"
    if observation["lock_state"] not in {"ACQUIRED", "TRACKING"}:
        return "STOP", f"目标 {args.target!r} 仅处于 {observation['lock_state']}；不使用旧帧目标继续移动。"
    assert isinstance(target, TargetCandidate)
    forward_p10_m = observation["forward_p10_m"]
    if forward_p10_m is None or forward_p10_m <= args.forward_clearance_m:
        return "STOP", f"前方中心 P10={forward_p10_m}，低于/缺少 {args.forward_clearance_m:.2f} m 安全阈值。"
    local_action, bearing_deg = target_action(
        int(observation["image_width"]),
        target.box,
        target.distance_m,
        args.standoff_m,
        args.distance_tolerance_m,
        args.camera_hfov_deg,
        args.turn_threshold_deg,
    )
    if local_action == "FORWARD":
        action = "forward_small" if target.distance_m <= args.standoff_m + args.small_step_band_m else "forward_1s"
    elif local_action == "TURN_LEFT":
        action = "turn_left_small"
    elif local_action == "TURN_RIGHT":
        action = "turn_right_small"
    else:
        action = "STOP"
    reason = (
        f"lock={observation['lock_state']}; distance={target.distance_m:.2f} m; "
        f"bearing={bearing_deg:+.1f}°; forward-P10={forward_p10_m:.2f} m."
    )
    if observation["person_visible"]:
        reason += " person 在画面中：仅由现场两次 MOVE 确认短路径是否清空。"
    return action, reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="YOLO 目标类别，例如 cup 或 bottle")
    parser.add_argument("--standoff-m", type=float, default=0.50)
    parser.add_argument("--distance-tolerance-m", type=float, default=0.05)
    parser.add_argument("--small-step-band-m", type=float, default=0.20, help="距停靠点此范围内改用 0.3 秒小步")
    parser.add_argument("--forward-clearance-m", type=float, default=0.20)
    parser.add_argument("--turn-threshold-deg", type=float, default=5.0)
    parser.add_argument("--camera-hfov-deg", type=float, default=90.0)
    parser.add_argument(
        "--max-actions",
        type=int,
        default=3,
        choices=range(1, 9),
        metavar="1..8",
        help="本次最多执行的固定动作数（默认 3；每步仍要求两次 MOVE）",
    )
    parser.add_argument("--execute", action="store_true", help="允许经两次 MOVE 确认后调用固定底盘单步脚本")
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--confidence", type=float, default=0.25, help="目标接近的 YOLO 置信度阈值（默认 0.25）")
    parser.add_argument("--lock-max-jump-px", type=float, default=180.0)
    parser.add_argument("--lock-lost-frames", type=int, default=2)
    parser.add_argument("--lock-smoothing", type=float, default=0.35)
    parser.add_argument("--frame-timeout-s", type=float, default=8.0)
    parser.add_argument("--target-search-s", type=float, default=4.0, help="每一步先等待目标重现的最长时间（默认 4 秒）")
    parser.add_argument("--sdk-hz", type=float, default=10.0)
    parser.add_argument("--depth-python", default=str(DEFAULT_DEPTH_PYTHON))
    parser.add_argument("--depth-sudo", action="store_true")
    parser.add_argument("--rgb-path", type=Path, default=RUNTIME_DIR / "target_approach_rgb.jpg")
    parser.add_argument("--depth-path", type=Path, default=RUNTIME_DIR / "target_approach_depth.npy")
    parser.add_argument("--metadata-path", type=Path, default=RUNTIME_DIR / "target_approach_metadata.json")
    args = parser.parse_args()
    if args.target == "person":
        raise SystemExit("person 不是允许的物理接近目标。")
    if not (
        0.20 <= args.standoff_m <= 1.00
        and 0 < args.confidence <= 1
        and args.forward_clearance_m >= MIN_VALID_M
        and args.target_search_s > 0
    ):
        raise SystemExit("停靠距离、置信度或前方安全阈值无效。")
    for path in (args.rgb_path, args.depth_path, args.metadata_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    sidecar = None
    try:
        print("启动本地 YOLO + 对齐 Gemini RGB-D 目标规划器…")
        print("DRY RUN：不会打开串口或移动底盘。" if not args.execute else "执行模式：每一步仍需两次 MOVE 确认。")
        sidecar = start_sidecar(args)
        model = YOLO(args.model)
        target_lock = TargetLock(args.lock_max_jump_px, args.lock_lost_frames, args.lock_smoothing)
        sequence = -1
        for step in range(1, args.max_actions + 1):
            if sidecar.poll() is not None:
                raise RuntimeError(f"Orbbec RGB-D sidecar 已退出（状态 {sidecar.returncode}）。")
            observation, sequence = read_observation(args, model, target_lock, sequence)
            # A small cup can fall below one-frame YOLO confidence because of
            # motion blur or exposure. Keep consuming fresh frames briefly;
            # only declare STOP after a bounded local search period.
            search_deadline = time.monotonic() + args.target_search_s
            while (
                observation["target"] is None
                or observation["lock_state"] not in {"ACQUIRED", "TRACKING"}
            ) and time.monotonic() < search_deadline:
                observation, sequence = read_observation(args, model, target_lock, sequence)
            action, reason = choose_action(args, observation)
            print(f"\n目标步骤 {step}/{args.max_actions}: {action} — {reason}")
            if action == "STOP":
                print("停止：未启动底盘。")
                break
            if not args.execute:
                print(f"DRY RUN：将执行 {action}；没有发送电机命令。")
                continue
            answer = input("确认目标短路径清空、双臂不会碰撞且可立即断开 12V；输入 MOVE 执行本步： ").strip()
            if answer != "MOVE":
                print("已取消；没有发送电机命令。")
                break
            print("调用已验证的固定底盘单步脚本；它将要求第二次 MOVE。")
            result = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "base_motion_step.py"), action], check=False)
            if result.returncode != 0:
                print(f"底盘单步脚本结束于状态 {result.returncode}；停止。")
                break
    finally:
        stop_process(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
