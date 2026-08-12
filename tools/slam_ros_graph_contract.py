#!/usr/bin/env python3
"""Validate the isolated camera-only RGB-D odometry ROS graph artifacts."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


EXPECTED_PUBLISHERS = {
    "odom": {"/rtabmap/rgbd_odometry"},
    "odom_info": {"/rtabmap/rgbd_odometry"},
    "tf": {"/camera/camera", "/rtabmap/rgbd_odometry"},
    "tf_static": {"/camera/camera"},
}


def _qualified_name(name: str, namespace: str) -> str:
    namespace = namespace.rstrip("/")
    return f"{namespace}/{name}" if namespace else f"/{name}"


def parse_publishers(text: str) -> tuple[int, list[str]]:
    count_match = re.search(r"^Publisher count:\s*(\d+)\s*$", text, re.MULTILINE)
    if count_match is None:
        raise ValueError("topic info is missing Publisher count")

    publishers: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        if "Endpoint type: PUBLISHER" not in block:
            continue
        name_match = re.search(r"^Node name:\s*(\S+)\s*$", block, re.MULTILINE)
        namespace_match = re.search(
            r"^Node namespace:\s*(\S+)\s*$", block, re.MULTILINE
        )
        if name_match is None or namespace_match is None:
            raise ValueError("publisher endpoint is missing node name or namespace")
        publishers.append(_qualified_name(name_match.group(1), namespace_match.group(1)))
    return int(count_match.group(1)), publishers


def parse_tf_chain(text: str) -> dict:
    errors: list[str] = []
    for block in re.split(r"(?=^At time\b)", text, flags=re.MULTILINE):
        if not block.startswith("At time"):
            continue
        time_match = re.search(r"^At time\s+([^\s]+)\s*$", block, re.MULTILINE)
        translation_match = re.search(
            r"^- Translation:\s*\[([^\]]+)\]\s*$", block, re.MULTILINE
        )
        quaternion_match = re.search(
            r"^- Rotation: in Quaternion(?:\s+\(xyzw\))?\s*\[([^\]]+)\]\s*$",
            block,
            re.MULTILINE,
        )
        if time_match is None or translation_match is None or quaternion_match is None:
            errors.append("transform block is incomplete")
            continue
        try:
            stamp = float(time_match.group(1))
            translation = [
                float(value.strip()) for value in translation_match.group(1).split(",")
            ]
            quaternion = [
                float(value.strip()) for value in quaternion_match.group(1).split(",")
            ]
        except ValueError:
            errors.append("transform block contains a non-numeric value")
            continue
        values = [stamp, *translation, *quaternion]
        if len(translation) != 3 or len(quaternion) != 4:
            errors.append("transform block has invalid vector dimensions")
            continue
        if not all(math.isfinite(value) for value in values):
            errors.append("transform block contains a non-finite value")
            continue
        if math.sqrt(sum(value * value for value in quaternion)) < 1e-9:
            errors.append("transform block contains a zero quaternion")
            continue
        return {
            "stamp_s": stamp,
            "translation": translation,
            "quaternion": quaternion,
        }
    detail = errors[-1] if errors else "no transform block was found"
    raise ValueError(detail)


def analyze_graph(topic_info: dict[str, str], tf_chain: str) -> dict:
    failures: list[str] = []
    observed: dict[str, dict] = {}

    for key, expected in EXPECTED_PUBLISHERS.items():
        try:
            declared_count, publisher_endpoints = parse_publishers(topic_info[key])
        except (KeyError, ValueError) as exc:
            failures.append(f"{key}: {exc}")
            continue
        publishers = set(publisher_endpoints)
        observed[key] = {
            "declared_publisher_count": declared_count,
            "parsed_endpoint_count": len(publisher_endpoints),
            "publishers": sorted(publishers),
        }
        if declared_count != len(publisher_endpoints):
            failures.append(
                f"{key}: declared {declared_count} publishers but parsed "
                f"{len(publisher_endpoints)} endpoints"
            )
        if len(publishers) != len(publisher_endpoints):
            failures.append(f"{key}: duplicate publisher endpoints were reported")
        if publishers != expected:
            failures.append(
                f"{key}: expected publishers {sorted(expected)}, got {sorted(publishers)}"
            )

    transform: dict | None = None
    try:
        transform = parse_tf_chain(tf_chain)
    except ValueError as exc:
        failures.append(f"tf_chain: {exc}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "expected_publishers": {
            key: sorted(value) for key, value in EXPECTED_PUBLISHERS.items()
        },
        "observed": observed,
        "tf_chain_observed": transform is not None,
        "transform": transform,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odom-topic-info", type=Path, required=True)
    parser.add_argument("--odom-info-topic-info", type=Path, required=True)
    parser.add_argument("--tf-topic-info", type=Path, required=True)
    parser.add_argument("--tf-static-topic-info", type=Path, required=True)
    parser.add_argument("--tf-chain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    topic_info = {
        "odom": args.odom_topic_info.read_text(encoding="utf-8"),
        "odom_info": args.odom_info_topic_info.read_text(encoding="utf-8"),
        "tf": args.tf_topic_info.read_text(encoding="utf-8"),
        "tf_static": args.tf_static_topic_info.read_text(encoding="utf-8"),
    }
    report = analyze_graph(topic_info, args.tf_chain.read_text(encoding="utf-8"))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
