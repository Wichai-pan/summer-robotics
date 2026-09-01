#!/usr/bin/env bash
# Coordinate foreground robot tasks with the opt-in idle camera monitor.
# Source this file, call forestbridge_task_guard_begin before the first
# hardware command, and forestbridge_task_guard_end from the outer EXIT trap.

forestbridge_task_guard_begin() {
  local data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
  local guard_dir="${FORESTBRIDGE_TASK_ACTIVE_DIR:-$data_root/runtime/forestbridge-task-active}"
  local lock_path="${FORESTBRIDGE_HARDWARE_LOCK:-/tmp/forestbridge-xlerobot.lock}"
  local wait_s="${FORESTBRIDGE_TASK_GUARD_WAIT_S:-25}"
  local owner_pid owner_start existing_pid existing_start

  # A pipeline owns one guard across its nested Nav2 and ACT wrappers.
  if [[ -n "${FORESTBRIDGE_TASK_GUARD_OWNER:-}" && -d "$guard_dir" ]]; then
    FORESTBRIDGE_TASK_GUARD_OWNED=false
    return 0
  fi

  mkdir -p "$(dirname "$guard_dir")"
  owner_pid="$$"
  owner_start="$(awk '{print $22}' "/proc/$owner_pid/stat")"

  if ! mkdir "$guard_dir" 2>/dev/null; then
    existing_pid="$(sed -n '1p' "$guard_dir/owner" 2>/dev/null || true)"
    existing_start="$(sed -n '2p' "$guard_dir/owner" 2>/dev/null || true)"
    if [[ -n "$existing_pid" && -r "/proc/$existing_pid/stat" ]] &&
       [[ "$(awk '{print $22}' "/proc/$existing_pid/stat" 2>/dev/null)" == "$existing_start" ]]; then
      echo "Another foreground robot task is active (PID $existing_pid)." >&2
      return 3
    fi
    rm -rf -- "$guard_dir"
    mkdir "$guard_dir"
  fi

  printf '%s\n%s\n' "$owner_pid" "$owner_start" >"$guard_dir/owner"
  export FORESTBRIDGE_TASK_GUARD_OWNER="$owner_pid:$owner_start"
  FORESTBRIDGE_TASK_GUARD_OWNED=true

  echo "Foreground task announced; waiting for any in-flight camera snapshot to release hardware."
  if ! flock --wait "$wait_s" "$lock_path" true; then
    echo "Timed out after ${wait_s}s waiting for the hardware lock: $lock_path" >&2
    forestbridge_task_guard_end
    return 3
  fi
}

forestbridge_task_guard_end() {
  local data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
  local guard_dir="${FORESTBRIDGE_TASK_ACTIVE_DIR:-$data_root/runtime/forestbridge-task-active}"
  local expected actual_pid actual_start

  [[ "${FORESTBRIDGE_TASK_GUARD_OWNED:-false}" == true ]] || return 0
  expected="${FORESTBRIDGE_TASK_GUARD_OWNER:-}"
  actual_pid="$(sed -n '1p' "$guard_dir/owner" 2>/dev/null || true)"
  actual_start="$(sed -n '2p' "$guard_dir/owner" 2>/dev/null || true)"
  if [[ "$actual_pid:$actual_start" == "$expected" ]]; then
    rm -rf -- "$guard_dir"
  fi
  FORESTBRIDGE_TASK_GUARD_OWNED=false
  unset FORESTBRIDGE_TASK_GUARD_OWNER
}
