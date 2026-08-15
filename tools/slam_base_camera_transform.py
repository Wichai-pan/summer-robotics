#!/usr/bin/env python3
"""Validate and manipulate a base_link-to-camera_link static transform."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path


SCHEMA = "forestbridge/slam/base-camera-transform/v1"


@dataclass(frozen=True)
class Transform:
    parent_frame: str
    child_frame: str
    translation_m: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]


def _finite_vector(data: object, field: str, length: int) -> tuple[float, ...]:
    if not isinstance(data, list) or len(data) != length:
        raise ValueError(f"{field} must be a list of {length} values")
    try:
        values = tuple(float(value) for value in data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain numeric values") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{field} must contain finite values")
    return values


def parse_transform_config(path: Path, *, require_live: bool = False) -> Transform | None:
    """Read the JSON-compatible YAML project config without a YAML dependency."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON-compatible YAML config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("transform config must be an object")
    if data.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    status = data.get("status")
    if status == "unresolved":
        if require_live:
            raise ValueError("transform config is unresolved and cannot be used for live mode")
        return None
    if status != "candidate":
        raise ValueError("status must be unresolved or candidate")
    if data.get("unit") != "m":
        raise ValueError("unit must be m")
    if data.get("parent_frame") != "base_link" or data.get("child_frame") != "camera_link":
        raise ValueError("parent_frame must be base_link and child_frame must be camera_link")
    translation = _finite_vector(data.get("translation_m"), "translation_m", 3)
    quaternion = _finite_vector(data.get("rotation_xyzw"), "rotation_xyzw", 4)
    norm = math.sqrt(sum(value * value for value in quaternion))
    if norm == 0.0:
        raise ValueError("rotation_xyzw must not be zero")
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f"rotation_xyzw must be normalized, got norm {norm:.9f}")
    if not isinstance(data.get("source_files"), list) or not data["source_files"]:
        raise ValueError("candidate config must list source_files")
    raw = data.get("gimbal_reference_raw")
    if not isinstance(raw, dict) or set(raw) != {"7", "8"}:
        raise ValueError("candidate config must contain gimbal_reference_raw keys 7 and 8")
    for motor_id, value in raw.items():
        if not isinstance(value, int) or not 0 <= value <= 4095:
            raise ValueError(f"gimbal_reference_raw[{motor_id}] must be an integer encoder raw value")
    if not any(key in data for key in ("uncertainty_m", "measurement_notes")):
        raise ValueError("candidate config must contain uncertainty_m or measurement_notes")
    return Transform("base_link", "camera_link", translation, quaternion)


def invert_transform(transform: Transform) -> Transform:
    x, y, z, w = transform.rotation_xyzw
    inverse_rotation = (-x, -y, -z, w)
    tx, ty, tz = transform.translation_m
    qx, qy, qz, qw = inverse_rotation
    rotated = (
        (1 - 2 * (qy * qy + qz * qz)) * tx + 2 * (qx * qy - qz * qw) * ty + 2 * (qx * qz + qy * qw) * tz,
        2 * (qx * qy + qz * qw) * tx + (1 - 2 * (qx * qx + qz * qz)) * ty + 2 * (qy * qz - qx * qw) * tz,
        2 * (qx * qz - qy * qw) * tx + 2 * (qy * qz + qx * qw) * ty + (1 - 2 * (qx * qx + qy * qy)) * tz,
    )
    return Transform(transform.child_frame, transform.parent_frame, tuple(-value for value in rotated), inverse_rotation)


def compose_transforms(left: Transform, right: Transform) -> Transform:
    if left.child_frame != right.parent_frame:
        raise ValueError("transform frames do not compose")
    ax, ay, az, aw = left.rotation_xyzw
    bx, by, bz, bw = right.rotation_xyzw
    rotation = (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )
    rx, ry, rz, rw = left.rotation_xyzw
    x, y, z = right.translation_m
    rotated = (
        (1 - 2 * (ry * ry + rz * rz)) * x + 2 * (rx * ry - rz * rw) * y + 2 * (rx * rz + ry * rw) * z,
        2 * (rx * ry + rz * rw) * x + (1 - 2 * (rx * rx + rz * rz)) * y + 2 * (ry * rz - rx * rw) * z,
        2 * (rx * rz - ry * rw) * x + 2 * (ry * rz + rx * rw) * y + (1 - 2 * (rx * rx + ry * ry)) * z,
    )
    return Transform(
        left.parent_frame,
        right.child_frame,
        tuple(a + b for a, b in zip(left.translation_m, rotated, strict=True)),
        rotation,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "static-transform-args"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--require-live", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        transform = parse_transform_config(args.config, require_live=args.require_live)
    except ValueError as exc:
        print(f"FAIL {exc}")
        return 1
    if transform is None:
        print("UNRESOLVED transform accepted for dry-run; live mode is prohibited")
        return 0
    if args.command == "static-transform-args":
        for value in (*transform.translation_m, *transform.rotation_xyzw, transform.parent_frame, transform.child_frame):
            print(value)
    else:
        print(f"PASS {transform.parent_frame} -> {transform.child_frame} candidate config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
