#!/usr/bin/env bash
set -euo pipefail

# Nav2 dry-run deliberately exposes Gemini and the read-only gimbal check only.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  --gemini --black --interactive -- \
  bash scripts/slam_nav2_planning_dry_run_container.sh "$@"
