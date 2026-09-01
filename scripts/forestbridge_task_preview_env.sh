#!/usr/bin/env bash
# Source the private relay token for task-owned camera previews.  This helper
# is intentionally silent and never prints secret values.

preview_env_file="${FORESTBRIDGE_RELAY_ENV_FILE:-/home/jetsonl7/robot-data/services/forestbridge-monitor/.env}"
if [[ -r "$preview_env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$preview_env_file"
  set +a
fi
if [[ -n "${FORESTBRIDGE_ROBOT_TOKEN:-}" ]]; then
  export FORESTBRIDGE_RELAY_URL="${FORESTBRIDGE_RELAY_URL:-https://robot.wichai.xyz}"
  export FORESTBRIDGE_TASK_PREVIEW="${FORESTBRIDGE_TASK_PREVIEW:-1}"
fi
