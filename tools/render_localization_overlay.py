#!/usr/bin/env python3
"""Render an RTAB-Map occupancy grid with the localized base pose overlaid.

The renderer intentionally uses only the Python standard library so it can run
inside the small ROS SLAM image. Its portable PPM output opens directly in macOS
Preview and makes a map-frame x/y result inspectable by an on-site operator.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


def read_pgm(path: Path) -> tuple[int, int, bytes]:
    raw = path.read_bytes()
    if not raw.startswith((b"P5", b"P2")):
        raise ValueError("occupancy image must be a P5 or P2 PGM")

    index = 0

    def token() -> bytes:
        nonlocal index
        while index < len(raw) and raw[index:index + 1].isspace():
            index += 1
        if index < len(raw) and raw[index:index + 1] == b"#":
            while index < len(raw) and raw[index:index + 1] not in {b"\n", b"\r"}:
                index += 1
            return token()
        start = index
        while index < len(raw) and not raw[index:index + 1].isspace():
            index += 1
        return raw[start:index]

    magic = token()
    width, height, maximum = (int(token()) for _ in range(3))
    if width <= 0 or height <= 0 or maximum != 255:
        raise ValueError("PGM must have positive dimensions and 8-bit pixels")
    if magic == b"P5":
        while index < len(raw) and raw[index:index + 1].isspace():
            index += 1
        pixels = raw[index:index + width * height]
    else:
        pixels = bytes(int(token()) for _ in range(width * height))
    if len(pixels) != width * height:
        raise ValueError("PGM pixel payload has an unexpected size")
    return width, height, pixels


def map_metadata(path: Path) -> tuple[float, float, float]:
    text = path.read_text(encoding="utf-8")
    resolution_match = re.search(r"^resolution:\s*([-+0-9.eE]+)\s*$", text, re.MULTILINE)
    origin_match = re.search(r"^origin:\s*\[\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\]", text, re.MULTILINE)
    if resolution_match is None or origin_match is None:
        raise ValueError("map YAML is missing resolution or origin")
    resolution = float(resolution_match.group(1))
    origin_x = float(origin_match.group(1))
    origin_y = float(origin_match.group(2))
    if not all(math.isfinite(value) for value in (resolution, origin_x, origin_y)) or resolution <= 0:
        raise ValueError("map YAML has invalid resolution/origin")
    return resolution, origin_x, origin_y


def pose_metadata(path: Path) -> tuple[float, float, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pose = payload["map_to_base_link"]
    x, y, _ = (float(value) for value in pose["translation"])
    qx, qy, qz, qw = (float(value) for value in pose["quaternion"])
    if not all(math.isfinite(value) for value in (x, y, qx, qy, qz, qw)):
        raise ValueError("localization pose contains a non-finite value")
    # Standard ROS yaw extraction. The base arrow is deliberately only a
    # visual cue; RTAB-Map/TF remains the authoritative machine interface.
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return x, y, yaw


def set_pixel(buffer: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < height:
        offset = (y * width + x) * 3
        buffer[offset:offset + 3] = bytes(color)


def draw_disk(buffer: bytearray, width: int, height: int, center_x: int, center_y: int, radius: int, color: tuple[int, int, int]) -> None:
    for offset_y in range(-radius, radius + 1):
        for offset_x in range(-radius, radius + 1):
            if offset_x * offset_x + offset_y * offset_y <= radius * radius:
                set_pixel(buffer, width, height, center_x + offset_x, center_y + offset_y, color)


def draw_line(buffer: bytearray, width: int, height: int, start_x: int, start_y: int, end_x: int, end_y: int, color: tuple[int, int, int]) -> None:
    steps = max(abs(end_x - start_x), abs(end_y - start_y), 1)
    for index in range(steps + 1):
        fraction = index / steps
        set_pixel(buffer, width, height, round(start_x + fraction * (end_x - start_x)), round(start_y + fraction * (end_y - start_y)), color)


def map_xy_to_pixel(x: float, y: float, *, resolution: float, origin_x: float, origin_y: float, height: int) -> tuple[int, int]:
    return (
        round((x - origin_x) / resolution),
        height - 1 - round((y - origin_y) / resolution),
    )


def path_metadata(path: Path) -> list[tuple[float, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise ValueError("Nav2 path JSON does not report PASS")
    poses = payload.get("poses_map_xyz")
    if not isinstance(poses, list) or len(poses) < 2:
        raise ValueError("Nav2 path JSON must contain at least two poses_map_xyz entries")
    result: list[tuple[float, float]] = []
    for index, pose in enumerate(poses):
        if not isinstance(pose, list) or len(pose) < 2:
            raise ValueError(f"Nav2 path pose {index} is malformed")
        x, y = float(pose[0]), float(pose[1])
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError(f"Nav2 path pose {index} is non-finite")
        result.append((x, y))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-pgm", type=Path, required=True)
    parser.add_argument("--map-yaml", type=Path, required=True)
    parser.add_argument("--pose-json", type=Path, required=True)
    parser.add_argument("--path-json", type=Path, help="optional Nav2 ComputePathToPose result")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    width, height, pixels = read_pgm(args.map_pgm)
    resolution, origin_x, origin_y = map_metadata(args.map_yaml)
    pose_x, pose_y, yaw = pose_metadata(args.pose_json)
    pixel_x, pixel_y = map_xy_to_pixel(
        pose_x, pose_y, resolution=resolution, origin_x=origin_x, origin_y=origin_y, height=height
    )
    if not (0 <= pixel_x < width and 0 <= pixel_y < height):
        raise SystemExit(
            "localized base pose falls outside exported occupancy grid: "
            f"map=({pose_x:.3f}, {pose_y:.3f}) pixel=({pixel_x}, {pixel_y})"
        )

    rgb = bytearray(channel for value in pixels for channel in (value, value, value))
    path_points: list[tuple[int, int]] = []
    if args.path_json is not None:
        for x, y in path_metadata(args.path_json):
            path_x, path_y = map_xy_to_pixel(
                x, y, resolution=resolution, origin_x=origin_x, origin_y=origin_y, height=height
            )
            if not (0 <= path_x < width and 0 <= path_y < height):
                raise SystemExit(
                    "Nav2 path falls outside exported occupancy grid: "
                    f"map=({x:.3f}, {y:.3f}) pixel=({path_x}, {path_y})"
                )
            path_points.append((path_x, path_y))
        for start, end in zip(path_points, path_points[1:]):
            draw_line(rgb, width, height, *start, *end, (30, 210, 80))
        draw_disk(rgb, width, height, *path_points[-1], 5, (250, 220, 30))
    # Map +x points right in the grid; map +y points up while image +y points
    # down, hence the minus sign in the vertical component.
    arrow_length = max(14, min(width, height) // 18)
    tip_x = round(pixel_x + math.cos(yaw) * arrow_length)
    tip_y = round(pixel_y - math.sin(yaw) * arrow_length)
    draw_line(rgb, width, height, pixel_x, pixel_y, tip_x, tip_y, (30, 100, 255))
    draw_disk(rgb, width, height, pixel_x, pixel_y, 5, (255, 40, 40))
    draw_disk(rgb, width, height, tip_x, tip_y, 3, (30, 100, 255))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(rgb))
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(args.output),
                "map_xy_m": [pose_x, pose_y],
                "pixel_xy": [pixel_x, pixel_y],
                "yaw_deg": math.degrees(yaw),
                "path_pose_count": len(path_points),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
