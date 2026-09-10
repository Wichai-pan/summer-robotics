#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/forestbridge_task_preview_env.sh"
source "$repo_root/scripts/forestbridge_broker_task_guard.sh"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

trap forestbridge_broker_task_guard_end EXIT
forestbridge_broker_task_guard_begin

"$repo_root/scripts/jetson_robot_exec.sh" \
  --host-network --black --white --interactive -- \
  bash /data/services/forestbridge-gemini-broker/slam_nav2_supervised_execute_container.sh \
    --external-camera "$@"
