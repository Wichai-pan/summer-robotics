#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_forestbridge_robot_worker.sh [--hardware-execute] [worker options]

Start the outbound-only ForestBridge Relay worker. The default is dry-run.
--hardware-execute enables the allow-listed hardware adapter, but a separate
fresh lease from scripts/jetson_arm_relay_worker.sh is still mandatory.
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/forestbridge_task_preview_env.sh"

mode="dry-run"
execute_args=()
forward_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hardware-execute)
      mode="hardware"
      execute_args=(--execute)
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) forward_args+=("$1"); shift ;;
  esac
done

if [[ -z "${FORESTBRIDGE_ROBOT_TOKEN:-}" ]]; then
  echo "Missing FORESTBRIDGE_ROBOT_TOKEN; check the private monitor/relay env file." >&2
  exit 2
fi

exec python3 "$repo_root/tools/forestbridge_robot_worker.py" \
  --relay "${FORESTBRIDGE_RELAY_URL:-https://robot.wichai.xyz}" \
  --token "$FORESTBRIDGE_ROBOT_TOKEN" \
  --robot-id jetson-primary \
  --output-root "${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}/relay-worker" \
  --repo-root "$repo_root" \
  --mode "$mode" \
  "${execute_args[@]}" \
  "${forward_args[@]}"
