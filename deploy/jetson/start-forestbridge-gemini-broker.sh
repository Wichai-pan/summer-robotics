#!/usr/bin/env bash
set -euo pipefail

service_root="/home/jetsonl7/robot-data/services/forestbridge-gemini-broker"
repo_root="/home/jetsonl7/summer-robotics-deploy"
pid_file="$service_root/broker.pid"
log_file="$service_root/broker.log"

if [[ -s "$pid_file" ]]; then
  existing_pid="$(<"$pid_file")"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    exit 0
  fi
fi

setsid bash -c '
  while true; do
    cd /home/jetsonl7/summer-robotics-deploy
    bash scripts/jetson_gemini_rgbd_broker.sh
    printf "broker exited with status %s; restarting\n" "$?"
    sleep 3
  done
' </dev/null >>"$log_file" 2>&1 &

printf '%s\n' "$!" >"$pid_file"
