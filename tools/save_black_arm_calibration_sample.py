#!/usr/bin/env python3
"""Save one paired black-arm / Gemini calibration observation.

This tool never opens a motor port and never opens the Gemini.  It combines:

* ``MEASURED_ENCODER_JSON`` and ``SAVED_TARGET_JSON`` printed by
  ``tools/arm_keyboard.py black`` while the arm is holding the marker; and
* the ``pick_plan.json`` generated at the same stationary pose by the Gemini
  RGB-D dry-run command.

The resulting JSONL file is the input to the later eye-to-hand fitting step.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def parse_pose(value: str, name: str) -> dict[str, float]:
    try:
        parsed = json.loads(value)
        return {joint: float(parsed[joint]) for joint in JOINTS}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"{name} 必须是包含六个关节的 JSON：{exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="same-pose Gemini pick_plan.json")
    parser.add_argument("--measured-encoder", required=True, help="text after MEASURED_ENCODER_JSON=")
    parser.add_argument("--saved-target", required=True, help="text after SAVED_TARGET_JSON=")
    parser.add_argument("--label", required=True, help="e.g. pose_01_left_high")
    parser.add_argument(
        "--output", type=Path,
        default=Path("calibration/black_arm_eye_to_hand_samples.jsonl"),
        help="append-only JSONL sample file",
    )
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        camera_xyz = [float(x) for x in plan["marker_camera_xyz_m"]]
        spread = float(plan["max_spread_m"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"无法读取 RGB-D plan：{exc}") from exc
    if len(camera_xyz) != 3 or spread > 0.012:
        raise SystemExit("拒绝保存：RGB-D 点不是三维点，或稳定性超过 12 mm。")

    record = {
        "schema": "black_arm_eye_to_hand_sample/v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "marker_camera_xyz_m": camera_xyz,
        "marker_centroid_spread_m": spread,
        "measured_encoder": parse_pose(args.measured_encoder, "--measured-encoder"),
        "saved_p_target": parse_pose(args.saved_target, "--saved-target"),
        "source_plan": str(args.plan.resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"已保存样本 {args.label} → {args.output}")
    print("marker_camera_xyz_m=", record["marker_camera_xyz_m"])
    print("提示：保持底盘和云台不动；至少采集 6 个空间分散且不接触桌面的姿态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
