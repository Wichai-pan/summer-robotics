#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORESTBRIDGE_IMAGE="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

# Reuse the existing device resolver, data mount, and global hardware lock.
exec "$repo_root/scripts/jetson_robot_exec.sh" "$@"
