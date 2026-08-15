#!/usr/bin/env bash
set -euo pipefail

# One locked owner for a single original-speed base pulse and simultaneous
# Gemini RGB-D odometry. This is deliberately separate from mapping/Nav2.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  --gemini --black --white --interactive -- \
  bash scripts/slam_base_odom_stop_diagnostic_container.sh "$@"
