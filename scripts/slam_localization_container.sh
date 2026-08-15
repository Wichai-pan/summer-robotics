#!/usr/bin/env bash
set -euo pipefail

# Camera-only localization from a finalized RTAB-Map database. This script has
# no base controller access and never publishes /cmd_vel.

duration=60
database=""
config="configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml"
gimbal_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"
camera_width=640
camera_height=480
camera_fps=30

usage() {
  cat <<'EOF'
Usage: slam_localization_container.sh --database /data/slam/mapping/.../rtabmap.db
       [--duration S] [--config PATH] [--gimbal-reference PATH]
       [--camera-width PX] [--camera-height PX] [--camera-fps HZ]

Loads a finalized RTAB-Map database in read-only localization mode and verifies
that RTAB-Map publishes map -> base_link. It opens only Gemini and performs a
read-only gimbal-reference check; it cannot command the base or arms.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database) database="${2:?missing database path}"; shift 2 ;;
    --duration) duration="${2:?missing duration}"; shift 2 ;;
    --config) config="${2:?missing transform config}"; shift 2 ;;
    --gimbal-reference) gimbal_reference="${2:?missing reference}"; shift 2 ;;
    --camera-width) camera_width="${2:?missing width}"; shift 2 ;;
    --camera-height) camera_height="${2:?missing height}"; shift 2 ;;
    --camera-fps) camera_fps="${2:?missing fps}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }
[[ -n "$database" ]] || { echo "--database is required" >&2; usage >&2; exit 2; }
[[ -s "$database" ]] || { echo "database is missing or empty: $database" >&2; exit 2; }

echo "[1/3] Read-only Gemini gimbal reference check (no torque write)."
python3 tools/gemini_gimbal_pose.py \
  --reference "$gimbal_reference" check --tolerance-deg 1.0

echo "[2/3] Validating fixed base_link -> camera_link transform."
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live

cat <<EOF
[3/3] Starting ${duration}s camera-only localization using:
  $database
No base serial device is exposed. No /cmd_vel is published. Keep the Gemini at
the saved mapping pose and point it toward a feature-rich mapped view.
EOF
read -r -p "Type LOCALIZE to open Gemini and start the read-only session: " answer
[[ "$answer" == "LOCALIZE" ]] || { echo "Cancelled before Gemini was opened."; exit 2; }

bash scripts/slam_static_odom_container.sh \
  --mode localization \
  --transform-config "$config" \
  --localization-db "$database" \
  --duration "$duration" \
  --camera-width "$camera_width" --camera-height "$camera_height" --camera-fps "$camera_fps" \
  --output-root /data/slam/localization

echo "PASS localization-only session. Inspect the printed /data/slam/localization timestamp directory."
