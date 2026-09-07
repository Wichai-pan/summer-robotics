#!/usr/bin/env python3
"""Apply a stricter stationary gate to a completed localization run."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = list(args.run_dir.glob("localization-odom-report.json"))
    if len(reports) != 1:
        raise SystemExit(f"expected one localization report in {args.run_dir}")
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    result = json.loads((args.run_dir / "localization-result.json").read_text(encoding="utf-8"))
    graph = json.loads((args.run_dir / "ros-graph-contract-post.json").read_text(encoding="utf-8"))
    samples = [
        json.loads(line)
        for line in (args.run_dir / "localization-odom.jsonl").read_text(encoding="utf-8").splitlines()
        if '"type":"odom"' in line
    ]
    positions = [sample["position"] for sample in samples]
    median_position = [statistics.median(position[axis] for position in positions) for axis in range(3)]
    deviations = sorted(math.dist(position, median_position) for position in positions)
    p95_deviation = deviations[min(len(deviations) - 1, int(0.95 * len(deviations)))]
    maximum_deviation = deviations[-1]
    start = report["start_position_m"]
    end = report["end_position_m"]
    net_drift = math.dist(start, end)
    mean_path_speed = report["path_length_m"] / report["duration_s"]
    failures: list[str] = []
    checks = {
        "upstream_status_pass": report.get("status") == "PASS",
        "graph_contract_pass": graph.get("status") == "PASS",
        "localization_result_pass": result.get("status") == "PASS",
        "rate_at_least_5_hz": report.get("rate_hz", 0) >= 5.0,
        "maximum_gap_at_most_0_5_s": report.get("maximum_gap_s", 99) <= 0.5,
        "zero_tracking_loss": report.get("lost_events") == 0,
        "net_static_drift_at_most_0_02_m": net_drift <= 0.02,
        "stationary_p95_deviation_at_most_0_01_m": p95_deviation <= 0.01,
        "stationary_maximum_deviation_at_most_0_02_m": maximum_deviation <= 0.02,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    payload = {
        "status": "PASS" if not failures else "FAIL",
        "run_dir": str(args.run_dir.resolve()),
        "checks": checks,
        "failures": failures,
        "metrics": {
            "rate_hz": report.get("rate_hz"),
            "maximum_gap_s": report.get("maximum_gap_s"),
            "lost_events": report.get("lost_events"),
            "net_static_drift_m": round(net_drift, 6),
            "path_length_m": report.get("path_length_m"),
            "mean_jitter_path_speed_mps": round(mean_path_speed, 6),
            "stationary_median_position_m": median_position,
            "stationary_p95_deviation_m": round(p95_deviation, 6),
            "stationary_maximum_deviation_m": round(maximum_deviation, 6),
            "map_to_base_link": result.get("map_to_base_link"),
        },
    }
    output = args.output or args.run_dir / "home-navigation-localization-gate.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
