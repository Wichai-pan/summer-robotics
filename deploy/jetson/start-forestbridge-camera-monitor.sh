#!/usr/bin/env bash
set -euo pipefail

service_root="/home/jetsonl7/robot-data/services/forestbridge-monitor"
pid_file="$service_root/monitor.pid"
log_file="$service_root/monitor.log"

if [[ -s "$pid_file" ]]; then
  existing_pid="$(<"$pid_file")"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    exit 0
  fi
fi

setsid bash -c '
  set -a
  . /home/jetsonl7/robot-data/services/forestbridge-monitor/.env
  set +a
  while true; do
    /usr/bin/python3 /home/jetsonl7/robot-data/services/forestbridge-monitor/forestbridge_camera_monitor.py \
      --interval-s 2.0 --poll-s 1.0
    printf "monitor exited with status %s; restarting\n" "$?"
    sleep 3
  done
' </dev/null >>"$log_file" 2>&1 &

printf '%s\n' "$!" >"$pid_file"
