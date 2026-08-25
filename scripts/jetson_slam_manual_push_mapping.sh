#!/usr/bin/env bash
set -euo pipefail

# Host entry point for manual-push RGB-D mapping. It intentionally does not
# expose the white/base serial board, so the container cannot command wheels.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  --gemini --black --interactive -- \
  bash scripts/slam_manual_push_mapping_container.sh "$@"
