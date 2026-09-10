#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_arm_relay_worker.sh [--preset NAME] [--duration-s N] [--arm-file PATH]

Create one short-lived, one-shot authorization for a single web-triggered
hardware task. This must be run by an onsite operator with the 12 V cutoff in
hand and all robot workspaces clear. It does not start a task by itself.
EOF
}

preset="table_pick_place_01"
duration_s="900"
arm_file="/tmp/forestbridge-relay-worker.arm.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preset) preset="${2:?missing value for --preset}"; shift 2 ;;
    --duration-s) duration_s="${2:?missing value for --duration-s}"; shift 2 ;;
    --arm-file) arm_file="${2:?missing value for --arm-file}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration_s" =~ ^[0-9]+$ ]] || { echo "--duration-s must be an integer" >&2; exit 2; }
(( duration_s >= 60 && duration_s <= 3600 )) || {
  echo "--duration-s must be between 60 and 3600" >&2
  exit 2
}
[[ "$preset" == "table_pick_place_01" ]] || {
  echo "preset is not allow-listed on this Jetson: $preset" >&2
  exit 2
}

echo "This authorizes ONE web-triggered $preset hardware task for $duration_s seconds."
echo "Keep the 12 V cutoff attended; clear the base route, arm workspace and cables."
read -r -p "Type ARM_WEB_DEMO to create the one-shot lease: " confirmation
if [[ "$confirmation" != "ARM_WEB_DEMO" ]]; then
  echo "Not armed; no file was written."
  exit 1
fi

umask 077
expires_epoch_s="$(( $(date +%s) + duration_s ))"
temporary_file="${arm_file}.tmp.$$"
printf '{"schema":"forestbridge/web-motion-arm/v1","token":"FORESTBRIDGE_WEB_DEMO_ARMED","preset":"%s","expires_epoch_s":%s}\n' \
  "$preset" "$expires_epoch_s" > "$temporary_file"
mv "$temporary_file" "$arm_file"
echo "Armed one task until epoch $expires_epoch_s: $arm_file"
