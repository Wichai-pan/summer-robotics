#!/usr/bin/env python3
"""Resolve and validate a named-pose continuous home navigation route."""

import argparse
import json
import math
from pathlib import Path

import yaml

try:
    from tools.resolve_home_workspace_pose import resolve_pose
except ModuleNotFoundError:
    from resolve_home_workspace_pose import resolve_pose


ALLOWED_POLICIES = {"bounded", "guarded", "liveness"}
ALLOWED_MOTION_MODES = {"forward_path", "holonomic_path"}


def resolve_route(route_file: Path, workspace_config: Path) -> list[dict]:
    payload = yaml.safe_load(route_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "forestbridge/home-nav-route/v1":
        raise ValueError("route schema must be forestbridge/home-nav-route/v1")
    legs = payload.get("legs")
    if not isinstance(legs, list) or not legs:
        raise ValueError("route must contain at least one leg")

    resolved = []
    seen_ids = set()
    for index, leg in enumerate(legs, 1):
        if not isinstance(leg, dict):
            raise ValueError(f"route leg {index} must be an object")
        leg_id = str(leg.get("id", "")).strip()
        pose_id = str(leg.get("pose_id", "")).strip()
        if not leg_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in leg_id):
            raise ValueError(f"route leg {index} has an invalid id")
        if leg_id in seen_ids:
            raise ValueError(f"duplicate route leg id: {leg_id}")
        seen_ids.add(leg_id)
        pose = resolve_pose(workspace_config, pose_id)
        policy = str(leg.get("wheel_visual_policy", "bounded"))
        if policy not in ALLOWED_POLICIES:
            raise ValueError(f"route leg {leg_id} has invalid wheel_visual_policy")
        motion_mode = str(leg.get("motion_mode", "forward_path"))
        if motion_mode not in ALLOWED_MOTION_MODES:
            raise ValueError(f"route leg {leg_id} has invalid motion_mode")
        dock_distance = float(leg.get("dock_entry_distance_m", 0.0))
        if not math.isfinite(dock_distance) or not 0.0 <= dock_distance <= 0.50:
            raise ValueError(f"route leg {leg_id} dock_entry_distance_m must be in [0, 0.50]")
        append_exact = leg.get("append_exact_goal", False)
        if not isinstance(append_exact, bool):
            raise ValueError(f"route leg {leg_id} append_exact_goal must be boolean")
        preplan_localization_s = leg.get("preplan_localization_s", 0)
        if not isinstance(preplan_localization_s, int) or not 0 <= preplan_localization_s <= 30:
            raise ValueError(f"route leg {leg_id} preplan_localization_s must be an integer in [0, 30]")
        resolved.append(
            {
                "id": leg_id,
                "pose_id": pose_id,
                **pose,
                "wheel_visual_policy": policy,
                "motion_mode": motion_mode,
                "dock_entry_distance_m": dock_distance,
                "append_exact_goal": append_exact,
                "preplan_localization_s": preplan_localization_s,
            }
        )
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--workspace-config", type=Path, required=True)
    parser.add_argument("--tsv", action="store_true")
    args = parser.parse_args()
    legs = resolve_route(args.route, args.workspace_config)
    if args.tsv:
        for leg in legs:
            print(
                "\t".join(
                    str(value)
                    for value in (
                        leg["id"], leg["x"], leg["y"], leg["yaw_deg"],
                        leg["wheel_visual_policy"], leg["dock_entry_distance_m"],
                        "true" if leg["append_exact_goal"] else "false", leg["motion_mode"],
                        leg["preplan_localization_s"],
                    )
                )
            )
    else:
        print(json.dumps({"legs": legs}, indent=2))


if __name__ == "__main__":
    main()
