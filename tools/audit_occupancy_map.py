#!/usr/bin/env python3
"""Audit conservative connected free space in a ROS occupancy PGM."""

from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path


def read_pgm(path: Path) -> tuple[int, int, bytearray]:
    with path.open("rb") as stream:
        tokens: list[bytes] = []
        while len(tokens) < 4:
            line = stream.readline()
            if not line:
                raise ValueError("incomplete PGM header")
            line = line.split(b"#", 1)[0]
            tokens.extend(line.split())
        if tokens[0] != b"P5" or int(tokens[3]) != 255:
            raise ValueError("only binary 8-bit PGM maps are supported")
        width, height = map(int, tokens[1:3])
        pixels = bytearray(stream.read(width * height))
    if len(pixels) != width * height:
        raise ValueError("truncated PGM pixel data")
    return width, height, pixels


def read_yaml(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if value.startswith("["):
            result[key] = [float(item) for item in value.strip("[]").split(",")]
        else:
            try:
                result[key] = float(value)
            except ValueError:
                result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-pgm", type=Path, required=True)
    parser.add_argument("--map-yaml", type=Path, required=True)
    parser.add_argument("--start-x", type=float, required=True)
    parser.add_argument("--start-y", type=float, required=True)
    parser.add_argument("--robot-radius-m", type=float, default=0.30)
    parser.add_argument("--safety-margin-m", type=float, default=0.05)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()

    width, height, pixels = read_pgm(args.map_pgm)
    metadata = read_yaml(args.map_yaml)
    resolution = float(metadata["resolution"])
    origin_x, origin_y, _ = metadata["origin"]  # type: ignore[misc]
    radius_cells = math.ceil((args.robot_radius_m + args.safety_margin_m) / resolution)
    free = [value >= 250 for value in pixels]
    blocked = [not value for value in free]

    traversable = [False] * (width * height)
    disk = [
        (dx, dy)
        for dy in range(-radius_cells, radius_cells + 1)
        for dx in range(-radius_cells, radius_cells + 1)
        if dx * dx + dy * dy <= radius_cells * radius_cells
    ]
    for y in range(height):
        for x in range(width):
            traversable[y * width + x] = free[y * width + x] and all(
                0 <= x + dx < width
                and 0 <= y + dy < height
                and not blocked[(y + dy) * width + x + dx]
                for dx, dy in disk
            )

    # ROS map origin is bottom-left; PGM row zero is top-left.
    sx = int((args.start_x - origin_x) / resolution)
    sy = height - 1 - int((args.start_y - origin_y) / resolution)
    start_index = sy * width + sx if 0 <= sx < width and 0 <= sy < height else -1
    reachable: set[int] = set()
    if start_index >= 0 and traversable[start_index]:
        queue = collections.deque([start_index])
        reachable.add(start_index)
        while queue:
            index = queue.popleft()
            x, y = index % width, index // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                neighbor = ny * width + nx
                if 0 <= nx < width and 0 <= ny < height and traversable[neighbor] and neighbor not in reachable:
                    reachable.add(neighbor)
                    queue.append(neighbor)

    def world_bounds(indices: set[int]) -> list[float] | None:
        if not indices:
            return None
        xs, ys = zip(*((index % width, index // width) for index in indices))
        return [
            round(origin_x + min(xs) * resolution, 3),
            round(origin_y + (height - 1 - max(ys)) * resolution, 3),
            round(origin_x + (max(xs) + 1) * resolution, 3),
            round(origin_y + (height - min(ys)) * resolution, 3),
        ]

    payload = {
        "status": "PASS" if reachable else "FAIL",
        "map_cells": [width, height],
        "resolution_m": resolution,
        "map_world_bounds_xyxy_m": [origin_x, origin_y, origin_x + width * resolution, origin_y + height * resolution],
        "robot_radius_m": args.robot_radius_m,
        "safety_margin_m": args.safety_margin_m,
        "conservative_clearance_cells": radius_cells,
        "start_map_xy_m": [args.start_x, args.start_y],
        "start_pixel_xy": [sx, sy],
        "start_is_traversable": start_index >= 0 and traversable[start_index],
        "free_cells": sum(free),
        "clearance_traversable_cells": sum(traversable),
        "reachable_cells_from_start": len(reachable),
        "reachable_area_m2": round(len(reachable) * resolution * resolution, 3),
        "reachable_world_bounds_xyxy_m": world_bounds(reachable),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.preview:
        rgb = bytearray(width * height * 3)
        for index, value in enumerate(pixels):
            color = (value, value, value)
            if traversable[index]:
                color = (160, 210, 255)
            if index in reachable:
                color = (80, 210, 100)
            rgb[index * 3:index * 3 + 3] = bytes(color)
        if start_index >= 0:
            for y in range(max(0, sy - 2), min(height, sy + 3)):
                for x in range(max(0, sx - 2), min(width, sx + 3)):
                    rgb[(y * width + x) * 3:(y * width + x) * 3 + 3] = b"\xff\x20\x20"
        args.preview.write_bytes(f"P6\n{width} {height}\n255\n".encode() + rgb)
    print(json.dumps(payload, indent=2))
    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main())
