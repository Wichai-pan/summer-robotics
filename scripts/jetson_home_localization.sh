#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
map_timestamp="${JETSON_HOME_MAP_TIMESTAMP:-20260902T194820Z}"
duration="${1:-30}"
if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 [DURATION_SECONDS]" >&2
  exit 2
fi
database="/workspace/artifacts/slam/${map_timestamp}/navigation-work/rtabmap-candidate-working.db"
if [[ ! -s "$repo_root/${database#/workspace/}" ]]; then
  echo "Missing candidate working copy for ${map_timestamp}: $database; audit/copy the selected database first." >&2
  exit 2
fi
exec bash "$repo_root/scripts/jetson_slam_localization.sh" \
  --database "$database" --duration "$duration" \
  --config configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml \
  --gimbal-reference /data/config/gemini_gimbal_mapping_down_20deg_v1.json
