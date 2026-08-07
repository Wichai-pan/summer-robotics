#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
samples="${1:-5}"

[[ "$samples" =~ ^[1-9][0-9]*$ ]] || { echo "samples must be a positive integer" >&2; exit 2; }
mkdir -p "$data_root/tmp"
touch "$data_root/tmp/jetson-gemini-smoke.jpg" "$data_root/tmp/jetson-gemini-smoke.json"

exec "$repo_root/scripts/jetson_robot_exec.sh" --gemini -- \
  python3 tools/orbbec_rgbd_snapshot.py \
  --samples "$samples" \
  --output /data/tmp/jetson-gemini-smoke.jpg \
  --metadata /data/tmp/jetson-gemini-smoke.json \
  --json
