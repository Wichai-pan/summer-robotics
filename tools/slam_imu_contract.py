#!/usr/bin/env python3
"""Validate Gemini IMU evidence and its robot_localization selection vector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


SCHEMA = "forestbridge/slam/gemini-imu/v1"
AXIS_INDEX = {"x": 9, "y": 10, "z": 11}


def validate(config_path: Path, ekf_path: Path, require_live: bool) -> dict:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("invalid Gemini IMU schema")
    expected = {
        "topic": "/camera/gyro_accel/sample",
        "message_type": "sensor_msgs/msg/Imu",
        "frame_id": "camera_accel_gyro_optical_frame",
        "orientation_available": False,
    }
    for field, value in expected.items():
        if data.get(field) != value:
            raise ValueError(f"Gemini IMU {field} must be {value!r}")
    if not require_live:
        return data
    axis = data.get("yaw_rate_axis")
    if (
        data.get("status") != "verified"
        or axis not in AXIS_INDEX
        or data.get("yaw_rate_sign_in_base") != 1
        or data.get("angular_velocity_covariance_verified") is not True
    ):
        raise ValueError(
            "Gemini base-yaw axis/covariance or positive post-TF sign are unresolved; live is blocked"
        )
    text = ekf_path.read_text(encoding="utf-8")
    block = text.split("imu0_config:", 1)[1].split("imu0_queue_size:", 1)[0]
    booleans = [value == "true" for value in re.findall(r"\b(?:true|false)\b", block)]
    if len(booleans) != 15:
        raise ValueError("imu0_config must contain 15 booleans")
    enabled = {index for index, value in enumerate(booleans) if value}
    if enabled != {AXIS_INDEX[axis]}:
        raise ValueError("imu0_config must enable only the verified yaw-rate source axis")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ekf-config", type=Path, required=True)
    parser.add_argument("--require-live", action="store_true")
    args = parser.parse_args()
    try:
        data = validate(args.config, args.ekf_config, args.require_live)
    except (OSError, json.JSONDecodeError, ValueError, IndexError) as exc:
        print(f"FAIL {exc}")
        return 1
    if data["status"] == "unresolved":
        print("UNRESOLVED Gemini IMU accepted for dry-run; fused live mode is prohibited")
    else:
        print("PASS Gemini IMU contract and EKF source axis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
