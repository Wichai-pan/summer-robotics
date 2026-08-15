#!/usr/bin/env bash
set -euo pipefail

# No --white: localization must not gain access to the base controller.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  --gemini --black --interactive -- \
  bash scripts/slam_localization_container.sh "$@"
