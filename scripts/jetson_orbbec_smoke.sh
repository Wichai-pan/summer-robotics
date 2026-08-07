#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
samples="${1:-5}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
image_host="$data_root/tmp/jetson-gemini-smoke-$stamp.jpg"
metadata_host="$data_root/tmp/jetson-gemini-smoke-$stamp.json"
image_container="/data/tmp/${image_host##*/}"
metadata_container="/data/tmp/${metadata_host##*/}"

[[ "$samples" =~ ^[1-9][0-9]*$ ]] || { echo "samples must be a positive integer" >&2; exit 2; }
mkdir -p "$data_root/tmp"
# Pre-create unique outputs as the host user. The root container truncates
# these existing files without changing ownership.
touch "$image_host" "$metadata_host"

echo "RGB output: $image_host"
echo "Metadata:   $metadata_host"

exec "$repo_root/scripts/jetson_robot_exec.sh" --gemini -- \
  python3 tools/orbbec_rgbd_snapshot.py \
  --samples "$samples" \
  --output "$image_container" \
  --metadata "$metadata_container" \
  --json
