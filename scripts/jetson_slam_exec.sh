#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/forestbridge_task_guard.sh"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

# Foreground SLAM/gimbal diagnostics must win the startup race with the idle
# camera monitor too. Nested Nav2/pipeline wrappers reuse their outer guard.
trap forestbridge_task_guard_end EXIT
forestbridge_task_guard_begin

# Reuse the existing device resolver, data mount, and global hardware lock.
"$repo_root/scripts/jetson_robot_exec.sh" "$@"
