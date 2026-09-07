#!/usr/bin/env python3
"""Reject a localization result that is inconsistent with a trusted parked pose."""

import argparse
import json
import math
from pathlib import Path


def wrap_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pose-json", type=Path, required=True)
    parser.add_argument("--expected-x", type=float, required=True)
    parser.add_argument("--expected-y", type=float, required=True)
    parser.add_argument("--expected-yaw-deg", type=float, required=True)
    parser.add_argument("--max-position-error-m", type=float, default=0.25)
    parser.add_argument("--max-yaw-error-deg", type=float, default=25.0)
    args = parser.parse_args()

    payload = json.loads(args.pose_json.read_text(encoding="utf-8"))
    tf = payload["map_to_base_link"]
    x, y = map(float, tf["translation"][:2])
    qx, qy, qz, qw = map(float, tf["quaternion"])
    yaw = math.degrees(math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz)))
    position_error = math.hypot(x - args.expected_x, y - args.expected_y)
    yaw_error = abs(wrap_deg(yaw - args.expected_yaw_deg))
    report = {
        "status": "PASS" if position_error <= args.max_position_error_m and yaw_error <= args.max_yaw_error_deg else "FAIL",
        "localized_pose": {"x": x, "y": y, "yaw_deg": yaw},
        "expected_pose": {"x": args.expected_x, "y": args.expected_y, "yaw_deg": args.expected_yaw_deg},
        "position_error_m": position_error,
        "yaw_error_deg": yaw_error,
        "limits": {"position_error_m": args.max_position_error_m, "yaw_error_deg": args.max_yaw_error_deg},
    }
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit("localization continuity gate failed; refusing planning and motion")


if __name__ == "__main__":
    main()
