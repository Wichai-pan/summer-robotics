#!/usr/bin/env python3
"""Analyze supervised moving RGB-D visual-odometry JSONL without ROS."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from tools.slam_static_odom_metrics import quaternion_distance_deg
except ModuleNotFoundError:
    from slam_static_odom_metrics import quaternion_distance_deg


@dataclass(frozen=True)
class MotionThresholds:
    minimum_duration_s: float = 10.0
    minimum_rate_hz: float = 5.0
    maximum_gap_s: float = 0.5
    maximum_lost_events: int = 0
    maximum_step_translation_m: float = 0.25
    maximum_step_rotation_deg: float = 45.0
    maximum_speed_mps: float = 1.0
    maximum_angular_speed_deg_s: float = 180.0


def _finite_vector(record: dict, key: str, length: int) -> tuple[float, ...]:
    values = record.get(key)
    if not isinstance(values, list) or len(values) != length:
        raise ValueError(f"{key} must contain {length} values")
    converted = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in converted):
        raise ValueError(f"{key} must contain finite values")
    return converted


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _analyze_records(records: Iterable[dict], thresholds: MotionThresholds | None = None) -> dict:
    limits = thresholds or MotionThresholds()
    odom = [record for record in records if record.get("type") == "odom"]
    info = [record for record in records if record.get("type") == "odom_info"]
    failures: list[str] = []
    if len(odom) < 2 or len(info) < 2:
        return {"status": "FAIL", "failures": ["need at least two odom and odom_info samples"], "thresholds": asdict(limits)}

    stamps = [float(record["stamp_s"]) for record in odom]
    received = [float(record["receive_monotonic_s"]) for record in odom]
    info_stamps = [float(record["stamp_s"]) for record in info]
    info_received = [float(record["receive_monotonic_s"]) for record in info]
    all_times = (*stamps, *received, *info_stamps, *info_received)
    if not all(math.isfinite(value) for value in all_times):
        failures.append("timestamps and receive times must be finite")
    if not all(b > a for a, b in zip(stamps, stamps[1:])):
        failures.append("odometry timestamps are not strictly monotonic")
    if not all(b > a for a, b in zip(received, received[1:])):
        failures.append("odometry receive times are not strictly monotonic")
    if not all(b > a for a, b in zip(info_stamps, info_stamps[1:])):
        failures.append("odometry-info timestamps are not strictly monotonic")
    if not all(b > a for a, b in zip(info_received, info_received[1:])):
        failures.append("odometry-info receive times are not strictly monotonic")
    if {record.get("frame_id") for record in odom} != {"odom"}:
        failures.append("odometry frame_id must be odom")
    if {record.get("child_frame_id") for record in odom} != {"base_link"}:
        failures.append("odometry child_frame_id must be base_link")

    positions = [_finite_vector(record, "position", 3) for record in odom]
    rotations = [_finite_vector(record, "orientation", 4) for record in odom]
    for rotation in rotations:
        norm = math.sqrt(sum(value * value for value in rotation))
        if norm == 0.0:
            failures.append("odometry orientation must not be a zero quaternion")
        elif not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
            failures.append(f"odometry orientation must be normalized, got norm {norm:.9f}")
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    receive_gaps = [b - a for a, b in zip(received, received[1:])]
    info_gaps = [b - a for a, b in zip(info_stamps, info_stamps[1:])]
    info_receive_gaps = [b - a for a, b in zip(info_received, info_received[1:])]
    steps = [_distance(a, b) for a, b in zip(positions, positions[1:])]
    turns = [quaternion_distance_deg(a, b) for a, b in zip(rotations, rotations[1:])]
    speeds = [distance / gap for distance, gap in zip(steps, gaps) if gap > 0.0]
    angular_speeds = [turn / gap for turn, gap in zip(turns, gaps) if gap > 0.0]
    duration = stamps[-1] - stamps[0]
    rate = (len(odom) - 1) / duration if duration > 0 else 0.0
    info_duration = info_stamps[-1] - info_stamps[0]
    info_rate = (len(info) - 1) / info_duration if info_duration > 0 else 0.0
    feature_values: list[int] = []
    inlier_values: list[int] = []
    for record in info:
        for field, destination in (("features", feature_values), ("inliers", inlier_values)):
            if field not in record:
                failures.append(f"odometry-info is missing {field}")
                continue
            try:
                destination.append(int(record[field]))
            except (TypeError, ValueError):
                failures.append(f"odometry-info {field} must be an integer")
    lost_events = sum(bool(record.get("lost", False)) for record in info)
    max_gap = max(*gaps, *receive_gaps, *info_gaps, *info_receive_gaps)
    max_step = max(steps)
    max_turn = max(turns)
    max_speed = max(speeds)
    max_angular_speed = max(angular_speeds)
    if duration < limits.minimum_duration_s:
        failures.append(f"duration {duration:.3f}s is below {limits.minimum_duration_s:.3f}s")
    if rate < limits.minimum_rate_hz or info_rate < limits.minimum_rate_hz:
        failures.append("odometry and odometry-info rate must meet minimum")
    if max_gap > limits.maximum_gap_s:
        failures.append(f"maximum message or receive gap {max_gap:.3f}s exceeds {limits.maximum_gap_s:.3f}s")
    if lost_events > limits.maximum_lost_events:
        failures.append(f"lost events {lost_events} exceed {limits.maximum_lost_events}")
    if max_step > limits.maximum_step_translation_m:
        failures.append(f"step translation {max_step:.3f}m exceeds {limits.maximum_step_translation_m:.3f}m")
    if max_turn > limits.maximum_step_rotation_deg:
        failures.append(f"step rotation {max_turn:.3f}deg exceeds {limits.maximum_step_rotation_deg:.3f}deg")
    if max_speed > limits.maximum_speed_mps:
        failures.append(f"estimated speed {max_speed:.3f}m/s exceeds {limits.maximum_speed_mps:.3f}m/s")
    if max_angular_speed > limits.maximum_angular_speed_deg_s:
        failures.append(f"estimated angular speed {max_angular_speed:.3f}deg/s exceeds {limits.maximum_angular_speed_deg_s:.3f}deg/s")
    segment_stats = {
        label: {"count": 0, "duration_s": 0.0, "path_length_m": 0.0, "rotation_deg": 0.0}
        for label in ("static", "straight", "turn")
    }
    for distance, turn, gap in zip(steps, turns, gaps):
        if distance < 0.005 and turn < 1.0:
            label = "static"
        elif turn >= 1.0:
            label = "turn"
        else:
            label = "straight"
        segment_stats[label]["count"] += 1
        segment_stats[label]["duration_s"] += gap
        segment_stats[label]["path_length_m"] += distance
        segment_stats[label]["rotation_deg"] += turn
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "odom_samples": len(odom), "odom_info_samples": len(info),
        "duration_s": round(duration, 6), "rate_hz": round(rate, 3),
        "odom_info_rate_hz": round(info_rate, 3), "maximum_gap_s": round(max_gap, 6),
        "path_length_m": round(sum(steps), 6), "start_position_m": positions[0], "end_position_m": positions[-1],
        "start_orientation_xyzw": rotations[0], "end_orientation_xyzw": rotations[-1],
        "maximum_step_translation_m": round(max_step, 6), "maximum_step_rotation_deg": round(max_turn, 6),
        "maximum_speed_mps": round(max_speed, 6), "maximum_angular_speed_deg_s": round(max_angular_speed, 6),
        "lost_events": lost_events,
        "segment_stats": {
            label: {key: round(value, 6) if isinstance(value, float) else value for key, value in values.items()}
            for label, values in segment_stats.items()
        },
        "median_features": statistics.median(feature_values) if feature_values else None,
        "median_inliers": statistics.median(inlier_values) if inlier_values else None,
        "thresholds": asdict(limits),
    }


def analyze_records(records: Iterable[dict], thresholds: MotionThresholds | None = None) -> dict:
    limits = thresholds or MotionThresholds()
    try:
        return _analyze_records(records, limits)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "failures": [f"invalid odometry record: {exc}"],
            "thresholds": asdict(limits),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-duration-s", type=float, default=10.0)
    parser.add_argument("--upstream-failure")
    args = parser.parse_args()
    records = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line]
    report = analyze_records(records, MotionThresholds(minimum_duration_s=args.minimum_duration_s))
    if args.upstream_failure:
        report["status"] = "FAIL"
        report.setdefault("failures", []).insert(0, args.upstream_failure)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
