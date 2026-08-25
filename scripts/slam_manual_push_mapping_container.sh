#!/usr/bin/env bash
set -euo pipefail

# Manual-push mapping deliberately opens no white/base serial device. The
# operator must verify that the wheels are already torque-free before moving.
duration=300
config="configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml"
gimbal_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"
camera_width=640
camera_height=480
camera_fps=30

usage() {
  cat <<'EOF'
Usage: slam_manual_push_mapping_container.sh [--duration S] [--config PATH]
       [--gimbal-reference PATH] [--camera-width PX] [--camera-height PX]
       [--camera-fps HZ]

Runs an RGB-D RTAB-Map mapping session for a person manually pushing the
robot. It opens Gemini and the read-only gimbal-reference check only; it does
not expose a base serial device, command wheels, or control either arm.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) duration="${2:?missing duration}"; shift 2 ;;
    --config) config="${2:?missing config}"; shift 2 ;;
    --gimbal-reference) gimbal_reference="${2:?missing reference}"; shift 2 ;;
    --camera-width) camera_width="${2:?missing width}"; shift 2 ;;
    --camera-height) camera_height="${2:?missing height}"; shift 2 ;;
    --camera-fps) camera_fps="${2:?missing fps}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }

echo "[1/3] Read-only Gemini gimbal reference check (no torque write)."
python3 tools/gemini_gimbal_pose.py \
  --reference "$gimbal_reference" check --tolerance-deg 1.0

echo "[2/3] Validating fixed base_link -> camera_link transform."
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live

cat <<EOF
[3/3] Manual-push mapping for ${duration}s.

This session has no access to the white/base serial device: it cannot enable
wheel torque or send wheel velocity. Before starting, confirm all wheels turn
freely by hand, clear the route, keep Gemini fixed, and hold the 12 V cutoff.

Push slowly and continuously. Prefer a broad loop plus one crossing pass; do
not stop at every step. Pause briefly only at visually distinctive places such
as wall corners, desk legs, or cabinet edges. Avoid people walking in front of
the camera during the recording.
EOF
read -r -p "Type MANUAL_MAP to open Gemini and start recording: " answer
[[ "$answer" == "MANUAL_MAP" ]] || { echo "Cancelled before Gemini was opened."; exit 2; }

bash scripts/slam_static_odom_container.sh \
  --mode mapping --transform-config "$config" --duration "$duration" \
  --camera-width "$camera_width" --camera-height "$camera_height" --camera-fps "$camera_fps" \
  --output-root /data/slam/mapping

echo "PASS manual-push mapping session. Inspect the printed /data/slam/mapping timestamp directory."
