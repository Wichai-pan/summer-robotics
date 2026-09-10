#!/usr/bin/env bash
# Select the persistent Gemini RGB-D broker when it is publishing fresh frames.
# Call forestbridge_gemini_broker_configure, then expand the two arrays around
# jetson_robot_exec.sh and the container entry point respectively.

forestbridge_gemini_broker_configure() {
  local data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
  local ready_file="${FORESTBRIDGE_GEMINI_BROKER_READY:-$data_root/runtime/forestbridge-gemini-broker.ready}"
  local shared_dir="${FORESTBRIDGE_GEMINI_SHARED_DIR:-/dev/shm/forestbridge-gemini}"
  local max_age_s="${FORESTBRIDGE_GEMINI_BROKER_MAX_AGE_S:-3}"
  local now_s frame_mtime age_s

  FORESTBRIDGE_GEMINI_DEVICE_ARGS=(--gemini)
  FORESTBRIDGE_GEMINI_CONTAINER_ARGS=()
  FORESTBRIDGE_GEMINI_BROKER_ACTIVE=false

  if [[ -s "$ready_file" && -s "$shared_dir/latest.jpg" && -s "$shared_dir/latest.json" ]]; then
    now_s="$(date +%s)"
    frame_mtime="$(stat -c %Y "$shared_dir/latest.json" 2>/dev/null || \
      stat -f %m "$shared_dir/latest.json" 2>/dev/null || printf '0')"
    age_s=$((now_s - frame_mtime))
    if ((age_s >= 0 && age_s <= max_age_s)); then
      FORESTBRIDGE_GEMINI_DEVICE_ARGS=(--host-network)
      FORESTBRIDGE_GEMINI_CONTAINER_ARGS=(--external-camera)
      FORESTBRIDGE_GEMINI_BROKER_ACTIVE=true
    fi
  fi
}
