#!/usr/bin/env bash
set -euo pipefail

# This is intentionally distinct from the planner-only wrapper: it exposes
# only Gemini, the black gimbal board, and the white board carrying wheel IDs
# 7/8/9. The execution script itself never commands white arm IDs 1-6.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  --gemini --black --white --interactive -- \
  bash scripts/slam_nav2_supervised_execute_container.sh "$@"
