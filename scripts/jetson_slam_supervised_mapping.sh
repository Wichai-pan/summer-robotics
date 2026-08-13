#!/usr/bin/env bash
set -euo pipefail

# Host entry point. It intentionally exposes only Gemini, the read-only black
# gimbal board, and the white base board to one locked SLAM container.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  --gemini --black --white --interactive -- \
  bash scripts/slam_supervised_mapping_container.sh "$@"
