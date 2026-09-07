#!/usr/bin/env bash
set -euo pipefail

if (($# < 2 || $# > 3)); then
  echo "Usage: $0 GOAL_X_M GOAL_Y_M [GOAL_YAW_DEG]" >&2
  exit 2
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
map_timestamp="${JETSON_HOME_MAP_TIMESTAMP:-20260902T194820Z}"

# Enter holonomic translation immediately: align to the supplied yaw, then
# move with body vx/vy while preserving that chassis heading.
exec bash "$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh" \
  --database "/workspace/artifacts/slam/${map_timestamp}/navigation-work/rtabmap-candidate-working.db" \
  --goal-x "$1" --goal-y "$2" --goal-yaw-deg "${3:-0}" \
  --duration 60 --robot-radius-m 0.30 \
  --max-path-m 0.30 --max-runtime-s 20 --max-tracked-travel-m 0.40 \
  --control-pose-source wheel --wheel-visual-policy bounded \
  --dock-entry-distance-m 0.25 --dock-yaw-align-tolerance-deg 2 \
  --dock-yaw-realign-tolerance-deg 5 \
  --position-tolerance-m 0.03 --yaw-tolerance-deg 2
