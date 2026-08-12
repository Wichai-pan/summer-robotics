#!/usr/bin/env python3
"""Analyze camera-only static RGB-D odometry samples without ROS dependencies."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Thresholds:
    minimum_duration_s: float = 50.0
    minimum_rate_hz: float = 5.0
    minimum_info_rate_hz: float = 5.0
    maximum_gap_s: float = 0.5
    maximum_translation_drift_m: float = 0.02
    maximum_rotation_drift_deg: float = 1.0
    maximum_lost_events: int = 0


def _vector(record: dict, key: str, length: int) -> tuple[float, ...]:
    values = tuple(float(value) for value in record[key])
    if len(values) != length or not all(math.isfinite(value) for value in values):
        raise ValueError(f"{key} must contain {length} finite values")
    return values


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def quaternion_distance_deg(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("orientation quaternion must be non-zero")
    dot = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return math.degrees(2.0 * math.acos(min(1.0, max(-1.0, abs(dot)))))


def analyze_records(records: Iterable[dict], thresholds: Thresholds | None = None) -> dict:
    limits = thresholds or Thresholds()
    odom = [record for record in records if record.get("type") == "odom"]
    info = [record for record in records if record.get("type") == "odom_info"]
    failures: list[str] = []

    if len(odom) < 2:
        return {
            "status": "FAIL",
            "failures": ["fewer than two odometry samples"],
            "odom_samples": len(odom),
            "odom_info_samples": len(info),
            "thresholds": asdict(limits),
        }
    if len(info) < 2:
        failures.append("fewer than two odometry-info samples")

    stamps = [float(record["stamp_s"]) for record in odom]
    receive_stamps = [float(record["receive_monotonic_s"]) for record in odom]
    if not all(math.isfinite(stamp) for stamp in stamps):
        raise ValueError("stamp_s values must be finite")
    if not all(math.isfinite(stamp) for stamp in receive_stamps):
        raise ValueError("receive_monotonic_s values must be finite")
    monotonic = all(current > previous for previous, current in zip(stamps, stamps[1:]))
    receive_monotonic = all(
        current > previous for previous, current in zip(receive_stamps, receive_stamps[1:])
    )
    gaps = [current - previous for previous, current in zip(stamps, stamps[1:])]
    receive_gaps = [
        current - previous for previous, current in zip(receive_stamps, receive_stamps[1:])
    ]
    duration_s = stamps[-1] - stamps[0]
    rate_hz = (len(stamps) - 1) / duration_s if duration_s > 0.0 else 0.0
    maximum_gap_s = max(gaps)
    maximum_receive_gap_s = max(receive_gaps)

    frame_ids = {str(record.get("frame_id", "")) for record in odom}
    child_frame_ids = {str(record.get("child_frame_id", "")) for record in odom}

    positions = [_vector(record, "position", 3) for record in odom]
    orientations = [_vector(record, "orientation", 4) for record in odom]
    translation_drift_m = _distance(positions[0], positions[-1])
    maximum_translation_excursion_m = max(_distance(positions[0], value) for value in positions)
    rotation_drift_deg = quaternion_distance_deg(orientations[0], orientations[-1])
    maximum_rotation_excursion_deg = max(
        quaternion_distance_deg(orientations[0], value) for value in orientations
    )

    lost_messages = sum(bool(record.get("lost", False)) for record in info)
    lost_events = 0
    previously_lost = False
    for record in info:
        lost = bool(record.get("lost", False))
        if lost and not previously_lost:
            lost_events += 1
        previously_lost = lost

    features = [int(record["features"]) for record in info if "features" in record]
    inliers = [int(record["inliers"]) for record in info if "inliers" in record]
    info_stamps = [float(record["stamp_s"]) for record in info]
    info_receive_stamps = [float(record["receive_monotonic_s"]) for record in info]
    if not all(math.isfinite(stamp) for stamp in info_stamps):
        raise ValueError("odometry-info stamp_s values must be finite")
    if not all(math.isfinite(stamp) for stamp in info_receive_stamps):
        raise ValueError("odometry-info receive_monotonic_s values must be finite")
    info_monotonic = len(info_stamps) >= 2 and all(
        current > previous for previous, current in zip(info_stamps, info_stamps[1:])
    )
    info_receive_monotonic = len(info_receive_stamps) >= 2 and all(
        current > previous
        for previous, current in zip(info_receive_stamps, info_receive_stamps[1:])
    )
    info_duration_s = info_stamps[-1] - info_stamps[0] if len(info_stamps) >= 2 else 0.0
    info_rate_hz = (
        (len(info_stamps) - 1) / info_duration_s if info_duration_s > 0.0 else 0.0
    )
    info_receive_gaps = [
        current - previous
        for previous, current in zip(info_receive_stamps, info_receive_stamps[1:])
    ]
    maximum_info_receive_gap_s = max(info_receive_gaps) if info_receive_gaps else 0.0

    if not monotonic:
        failures.append("odometry timestamps are not strictly monotonic")
    if not receive_monotonic:
        failures.append("odometry receive times are not strictly monotonic")
    if frame_ids != {"odom"}:
        failures.append(f"odometry frame_id must be odom, got {sorted(frame_ids)}")
    if child_frame_ids != {"camera_link"}:
        failures.append(
            f"odometry child_frame_id must be camera_link, got {sorted(child_frame_ids)}"
        )
    if duration_s < limits.minimum_duration_s:
        failures.append(
            f"duration {duration_s:.3f}s is below {limits.minimum_duration_s:.3f}s"
        )
    if rate_hz < limits.minimum_rate_hz:
        failures.append(f"rate {rate_hz:.3f}Hz is below {limits.minimum_rate_hz:.3f}Hz")
    if maximum_gap_s > limits.maximum_gap_s:
        failures.append(
            f"maximum gap {maximum_gap_s:.3f}s exceeds {limits.maximum_gap_s:.3f}s"
        )
    if maximum_receive_gap_s > limits.maximum_gap_s:
        failures.append(
            "maximum receive gap "
            f"{maximum_receive_gap_s:.3f}s exceeds {limits.maximum_gap_s:.3f}s"
        )
    if len(info) >= 2 and not info_monotonic:
        failures.append("odometry-info timestamps are not strictly monotonic")
    if len(info) >= 2 and not info_receive_monotonic:
        failures.append("odometry-info receive times are not strictly monotonic")
    if info_duration_s < limits.minimum_duration_s:
        failures.append(
            "odometry-info duration "
            f"{info_duration_s:.3f}s is below {limits.minimum_duration_s:.3f}s"
        )
    if info_rate_hz < limits.minimum_info_rate_hz:
        failures.append(
            f"odometry-info rate {info_rate_hz:.3f}Hz is below "
            f"{limits.minimum_info_rate_hz:.3f}Hz"
        )
    if maximum_info_receive_gap_s > limits.maximum_gap_s:
        failures.append(
            "maximum odometry-info receive gap "
            f"{maximum_info_receive_gap_s:.3f}s exceeds {limits.maximum_gap_s:.3f}s"
        )
    if maximum_translation_excursion_m > limits.maximum_translation_drift_m:
        failures.append(
            "maximum translation excursion "
            f"{maximum_translation_excursion_m:.4f}m exceeds "
            f"{limits.maximum_translation_drift_m:.4f}m"
        )
    if maximum_rotation_excursion_deg > limits.maximum_rotation_drift_deg:
        failures.append(
            "maximum rotation excursion "
            f"{maximum_rotation_excursion_deg:.3f}deg exceeds "
            f"{limits.maximum_rotation_drift_deg:.3f}deg"
        )
    if lost_events > limits.maximum_lost_events:
        failures.append(
            f"lost events {lost_events} exceed {limits.maximum_lost_events}"
        )

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "odom_samples": len(odom),
        "odom_info_samples": len(info),
        "timestamps_strictly_monotonic": monotonic,
        "receive_times_strictly_monotonic": receive_monotonic,
        "frame_ids": sorted(frame_ids),
        "child_frame_ids": sorted(child_frame_ids),
        "duration_s": round(duration_s, 6),
        "rate_hz": round(rate_hz, 3),
        "median_gap_s": round(statistics.median(gaps), 6),
        "maximum_gap_s": round(maximum_gap_s, 6),
        "maximum_receive_gap_s": round(maximum_receive_gap_s, 6),
        "odom_info_timestamps_strictly_monotonic": info_monotonic,
        "odom_info_receive_times_strictly_monotonic": info_receive_monotonic,
        "odom_info_duration_s": round(info_duration_s, 6),
        "odom_info_rate_hz": round(info_rate_hz, 3),
        "maximum_odom_info_receive_gap_s": round(maximum_info_receive_gap_s, 6),
        "translation_drift_m": round(translation_drift_m, 6),
        "maximum_translation_excursion_m": round(maximum_translation_excursion_m, 6),
        "rotation_drift_deg": round(rotation_drift_deg, 6),
        "maximum_rotation_excursion_deg": round(maximum_rotation_excursion_deg, 6),
        "lost_messages": lost_messages,
        "lost_events": lost_events,
        "median_features": statistics.median(features) if features else None,
        "median_inliers": statistics.median(inliers) if inliers else None,
        "thresholds": asdict(limits),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL captured by capture_static_odom.py")
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    parser.add_argument("--minimum-duration-s", type=float, default=50.0)
    parser.add_argument("--minimum-rate-hz", type=float, default=5.0)
    parser.add_argument("--minimum-info-rate-hz", type=float, default=5.0)
    parser.add_argument("--maximum-gap-s", type=float, default=0.5)
    parser.add_argument("--maximum-translation-drift-m", type=float, default=0.02)
    parser.add_argument("--maximum-rotation-drift-deg", type=float, default=1.0)
    parser.add_argument("--maximum-lost-events", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    thresholds = Thresholds(
        minimum_duration_s=args.minimum_duration_s,
        minimum_rate_hz=args.minimum_rate_hz,
        minimum_info_rate_hz=args.minimum_info_rate_hz,
        maximum_gap_s=args.maximum_gap_s,
        maximum_translation_drift_m=args.maximum_translation_drift_m,
        maximum_rotation_drift_deg=args.maximum_rotation_drift_deg,
        maximum_lost_events=args.maximum_lost_events,
    )
    with args.input.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    report = analyze_records(records, thresholds)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
