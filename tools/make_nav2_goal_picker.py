#!/usr/bin/env python3
"""Create an offline click-to-coordinate picker for a Nav2 occupancy-map image.

The generated page is self-contained. Clicking any observed free cell shows the
map-frame x/y coordinates and a ready-to-paste planner-only dry-run command.
It never opens a robot connection or emits a velocity command.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-yaml", type=Path, required=True)
    parser.add_argument("--map-image", type=Path, required=True, help="PNG map or overlay image")
    parser.add_argument("--database", required=True, help="container-visible RTAB-Map database path")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def metadata(path: Path) -> tuple[float, float, float]:
    text = path.read_text(encoding="utf-8")
    resolution = re.search(r"^resolution:\s*([-+0-9.eE]+)\s*$", text, re.MULTILINE)
    origin = re.search(
        r"^origin:\s*\[\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\]",
        text,
        re.MULTILINE,
    )
    if resolution is None or origin is None:
        raise ValueError("map YAML needs resolution and origin")
    return float(resolution.group(1)), float(origin.group(1)), float(origin.group(2))


def png_size(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError("--map-image must be a PNG")
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


def main() -> int:
    args = parse_args()
    resolution, origin_x, origin_y = metadata(args.map_yaml)
    width, height = png_size(args.map_image)
    image_b64 = base64.b64encode(args.map_image.read_bytes()).decode("ascii")
    payload = {
        "resolution": resolution,
        "originX": origin_x,
        "originY": origin_y,
        "width": width,
        "height": height,
        "database": args.database,
    }
    html = f"""<!doctype html>
<meta charset=\"utf-8\">
<title>ForestBridge Nav2 goal picker</title>
<style>
  body {{ margin: 24px; background: #17191d; color: #e8eaed; font: 15px -apple-system, BlinkMacSystemFont, sans-serif; }}
  main {{ max-width: 920px; margin: auto; }}
  #map {{ width: min(100%, 760px); image-rendering: pixelated; cursor: crosshair; border: 1px solid #454a52; display:block; }}
  code, pre {{ background:#24282e; padding:12px; border-radius:6px; display:block; overflow-x:auto; white-space:pre-wrap; }}
  .hint {{ color:#b8c2ce; }} .value {{ color:#7ee787; font-weight:600; }}
</style>
<main>
  <h2>Nav2 目标点选取</h2>
  <p class=\"hint\">只在浅色已观测空地点击；黑色是障碍，深灰是未知。此页面只换算坐标，不连接机器人。</p>
  <img id=\"map\" alt=\"occupancy map goal picker\" src=\"data:image/png;base64,{image_b64}\">
  <p id=\"selection\">点击地图选择目标。</p>
  <pre id=\"command\"></pre>
</main>
<script>
const config = {json.dumps(payload)};
const map = document.getElementById('map');
const selection = document.getElementById('selection');
const command = document.getElementById('command');
map.addEventListener('click', (event) => {{
  const rect = map.getBoundingClientRect();
  const px = Math.max(0, Math.min(config.width - 1, Math.floor((event.clientX - rect.left) * config.width / rect.width)));
  const py = Math.max(0, Math.min(config.height - 1, Math.floor((event.clientY - rect.top) * config.height / rect.height)));
  const x = config.originX + (px + 0.5) * config.resolution;
  const y = config.originY + (config.height - py - 0.5) * config.resolution;
  selection.innerHTML = `已选像素 (${{px}}, ${{py}})，目标 <span class=\"value\">x=${{x.toFixed(3)}} m, y=${{y.toFixed(3)}} m</span>`;
  command.textContent = `cd /home/jetsonl7/robot-data/tmp/slam-cleanup-tuning-20260813\n\nbash scripts/jetson_slam_nav2_planning_dry_run.sh \\\n  --database ${{config.database}} \\\n  --goal-x ${{x.toFixed(3)}} \\\n  --goal-y ${{y.toFixed(3)}} \\\n  --goal-yaw-deg 0 \\\n  --duration 60 \\\n  --robot-radius-m 0.30`;
}});
</script>
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"wrote {args.output} for {width}x{height} map at {resolution:.3f} m/pixel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
