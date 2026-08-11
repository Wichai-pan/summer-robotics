#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
mkdir -p "$data_root/slam/preflight"

# Gemini is the only device exposed. No controller serial port is mapped.
exec "$repo_root/scripts/jetson_slam_exec.sh" --gemini -- \
  bash scripts/slam_camera_preflight_container.sh /data/slam/preflight
