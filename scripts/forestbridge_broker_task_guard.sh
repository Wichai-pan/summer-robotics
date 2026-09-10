#!/usr/bin/env bash
# Foreground marker for tasks that consume the persistent Gemini broker.
# It intentionally does not wait for gemini.lock: that lock belongs to the
# healthy broker for its entire lifetime.

forestbridge_broker_task_guard_begin() {
  local data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
  local guard_dir="${FORESTBRIDGE_TASK_ACTIVE_DIR:-$data_root/runtime/forestbridge-task-active}"
  local shared_dir="${FORESTBRIDGE_GEMINI_SHARED_DIR:-/dev/shm/forestbridge-gemini}"
  local owner_pid owner_start existing_pid existing_start now_s frame_mtime

  [[ -s "$data_root/runtime/forestbridge-gemini-broker.ready" &&
     -s "$shared_dir/latest.json" ]] || {
    echo "Persistent Gemini broker is not ready." >&2
    return 3
  }
  now_s="$(date +%s)"
  frame_mtime="$(stat -c %Y "$shared_dir/latest.json" 2>/dev/null || printf '0')"
  ((now_s - frame_mtime >= 0 && now_s - frame_mtime <= 3)) || {
    echo "Persistent Gemini broker frame is stale." >&2
    return 3
  }

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
  FORESTBRIDGE_BROKER_GUARD_DIR="$guard_dir"
  FORESTBRIDGE_BROKER_GUARD_OWNER="$owner_pid:$owner_start"
  echo "Foreground task announced; Gemini remains continuously shared through the broker."
}

forestbridge_broker_task_guard_end() {
  local guard_dir="${FORESTBRIDGE_BROKER_GUARD_DIR:-}"
  local owner="${FORESTBRIDGE_BROKER_GUARD_OWNER:-}"
  local actual_pid actual_start
  [[ -n "$guard_dir" && -n "$owner" ]] || return 0
  actual_pid="$(sed -n '1p' "$guard_dir/owner" 2>/dev/null || true)"
  actual_start="$(sed -n '2p' "$guard_dir/owner" 2>/dev/null || true)"
  if [[ "$actual_pid:$actual_start" == "$owner" ]]; then
    rm -rf -- "$guard_dir"
  fi
  unset FORESTBRIDGE_BROKER_GUARD_DIR FORESTBRIDGE_BROKER_GUARD_OWNER
}
