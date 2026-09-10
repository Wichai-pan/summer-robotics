#!/usr/bin/env bash
set -euo pipefail

# No --white: localization must not gain access to the base controller.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/forestbridge_gemini_broker_env.sh"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

forestbridge_gemini_broker_configure

exec "$repo_root/scripts/jetson_slam_exec.sh" \
  "${FORESTBRIDGE_GEMINI_DEVICE_ARGS[@]}" --black --interactive -- \
  bash scripts/slam_localization_container.sh \
    "${FORESTBRIDGE_GEMINI_CONTAINER_ARGS[@]}" "$@"
