#!/usr/bin/env python3
"""Validate the no-LiDAR fused-SLAM topic and TF ownership contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCHEMA = "forestbridge/slam/fused-graph/v1"
EXPECTED_TF = {
    "base_link->camera_link": "base_to_gemini_static_tf",
    "odom->base_link": "ekf_filter_node",
    "map->odom": "rtabmap",
}


def validate_contract(data: dict) -> None:
    if data.get("schema") != SCHEMA:
        raise ValueError("invalid fused graph schema")
    owners = data.get("tf_owners")
    if owners != EXPECTED_TF:
        raise ValueError(f"TF owners must be exactly {EXPECTED_TF}")
    if len(set(owners.values())) != len(owners):
        raise ValueError("one node cannot silently own multiple formal TF edges")
    topics = data.get("topics", {})
    if topics.get("/odom", {}).get("publisher") != "ekf_filter_node":
        raise ValueError("/odom must be published by robot_localization")
    white_board = data.get("hardware_ownership", {}).get("white_board", {})
    expected_white_board = {
        "owner": "base_wheel_odometry",
        "motor_ids": [7, 8, 9],
        "readers": ["base_wheel_odometry"],
        "writers": ["base_wheel_odometry"],
    }
    if white_board != expected_white_board:
        raise ValueError(
            "white-board serial must have one owner restricted to wheel IDs 7/8/9"
        )
    forbidden_topics = set(data.get("forbidden_topics", []))
    forbidden_nodes = set(data.get("forbidden_nodes", []))
    if "/scan" not in forbidden_topics or not {"rgbd_odometry", "slam_toolbox"} <= forbidden_nodes:
        raise ValueError("no-LiDAR route guards are incomplete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_contract(json.loads(args.config.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL {exc}")
        return 1
    print("PASS fused graph contract; TF publishers are exclusive and no LiDAR path is present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
