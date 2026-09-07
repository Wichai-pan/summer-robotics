#!/usr/bin/env python3
"""Resolve a named home workspace pose from the navigation YAML."""

import argparse
import json
from pathlib import Path

import yaml


def resolve_pose(config: Path, pose_id: str) -> dict[str, float]:
    try:
        workspace_id, field = pose_id.split(".", 1)
    except ValueError as exc:
        raise ValueError("pose id must look like right_c.predock_pose") from exc
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    matches = [item for item in payload["workspaces"] if item.get("id") == workspace_id]
    if len(matches) != 1 or field not in matches[0] or matches[0][field] is None:
        raise ValueError(f"unknown or empty workspace pose: {pose_id}")
    pose = matches[0][field]
    return {key: float(pose[key]) for key in ("x", "y", "yaw_deg")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pose-id", required=True)
    parser.add_argument("--tsv", action="store_true")
    args = parser.parse_args()
    pose = resolve_pose(args.config, args.pose_id)
    if args.tsv:
        print(f"{pose['x']}\t{pose['y']}\t{pose['yaw_deg']}")
    else:
        print(json.dumps({"pose_id": args.pose_id, **pose}, indent=2))


if __name__ == "__main__":
    main()
