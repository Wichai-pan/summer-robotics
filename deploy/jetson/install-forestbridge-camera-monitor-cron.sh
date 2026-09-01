#!/usr/bin/env bash
set -euo pipefail

service_root="/home/jetsonl7/robot-data/services/forestbridge-monitor"
launcher="$service_root/start-forestbridge-camera-monitor.sh"
cron_line="@reboot $launcher"
cron_file="$(mktemp /tmp/forestbridge-monitor-cron.XXXXXX)"
trap 'rm -f "$cron_file"' EXIT

crontab -l >"$cron_file" 2>/dev/null || true
if ! grep -Fqx "$cron_line" "$cron_file"; then
  printf '%s\n' "$cron_line" >>"$cron_file"
  crontab "$cron_file"
fi

systemctl --user disable --now forestbridge-camera-monitor.service >/dev/null 2>&1 || true
"$launcher"
