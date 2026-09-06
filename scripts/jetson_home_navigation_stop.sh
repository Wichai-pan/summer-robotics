#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"
source "$repo_root/scripts/forestbridge_task_guard.sh"
trap forestbridge_task_guard_end EXIT
forestbridge_task_guard_begin

# Stop every project hardware session first. Its EXIT cleanup gets the first
# chance to brake; the dedicated zero/torque-off pass below verifies the bus.
mapfile -t sessions < <(docker ps --format '{{.Names}}' | sed -n '/^forestbridge-session-/p')
if ((${#sessions[@]})); then
  docker stop --time 10 "${sessions[@]}" >/dev/null
fi

"$repo_root/scripts/jetson_robot_exec.sh" --white -- \
  python3 tools/base_emergency_stop.py
