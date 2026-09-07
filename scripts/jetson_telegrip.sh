#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
black_link="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D043224-if00"
white_link="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D040988-if00"
cert="$repo_root/certs/telegrip/cert.pem"
key="$repo_root/certs/telegrip/key.pem"
vr_only=false

if [[ "${1:-}" == "--vr-only" ]]; then
  vr_only=true
  shift
fi

[[ -r "$cert" ]] || { echo "Missing TeleGrip certificate: $cert" >&2; exit 2; }
[[ -r "$key" ]] || { echo "Missing TeleGrip key: $key" >&2; exit 2; }

robot_exec_args=(--host-network --interactive)
telegrip_args=()
if [[ "$vr_only" == true ]]; then
  telegrip_args+=(--no-robot --no-sim)
  echo "Starting VR-only TeleGrip (no motor devices are mapped)."
else
  [[ -e "$black_link" ]] || { echo "Missing black arm: $black_link" >&2; exit 2; }
  [[ -e "$white_link" ]] || { echo "Missing white arm: $white_link" >&2; exit 2; }
  black_port="$(readlink -f "$black_link")"
  white_port="$(readlink -f "$white_link")"
  robot_exec_args=(--black --white "${robot_exec_args[@]}")
  telegrip_args+=(
    --left-port "$black_port"
    --right-port "$white_port"
    --left-id black_arm
    --right-id white_arm_leader_follow
  )
  echo "Motors remain torque-free until Connect Robot is explicitly selected."
fi

echo "Starting direct TeleGrip on https://192.168.1.164:8443"

exec "$repo_root/scripts/jetson_robot_exec.sh" \
  "${robot_exec_args[@]}" -- \
  env PYTHONPATH=/workspace/external/telegrip:/opt/lerobot/src \
  python3 -m telegrip \
  --no-viz \
  --no-keyboard \
  --log-level info \
  --config /workspace/external/telegrip/config.yaml \
  --urdf /workspace/external/telegrip/URDF/SO100/so100.urdf \
  --cert /workspace/certs/telegrip/cert.pem \
  --key /workspace/certs/telegrip/key.pem \
  "${telegrip_args[@]}" \
  "$@"
