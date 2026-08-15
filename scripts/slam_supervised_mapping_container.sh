#!/usr/bin/env bash
set -euo pipefail

# One owner for Gemini, the white base controller and the ROS mapping graph.
# This script is deliberately launched only through jetson_slam_exec.sh, whose
# one host-side flock protects all hardware exposed below.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
duration=120
config="configs/slam/base_to_gemini_candidate.yaml"
gimbal_reference="/data/config/gemini_gimbal_level_forward_v1.json"
xy_speed=0.04
theta_speed=12
camera_width=640
camera_height=480
camera_fps=30

usage() {
  cat <<'EOF'
Usage: slam_supervised_mapping_container.sh [--duration S] [--config PATH]
       [--gimbal-reference PATH] [--xy-speed-mps MPS] [--theta-speed-deg-s DEG_S]
       [--camera-width PX] [--camera-height PX] [--camera-fps HZ]

Runs one supervised, manual RGB-D mapping session. It first checks the fixed
Gemini pose read-only, then starts Gemini + static TF + RGB-D odometry +
RTAB-Map mapping. The base keyboard remains low-speed and terminal dead-man
protected. No arm controller is exposed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) duration="${2:?missing duration}"; shift 2 ;;
    --config) config="${2:?missing config}"; shift 2 ;;
    --gimbal-reference) gimbal_reference="${2:?missing reference}"; shift 2 ;;
    --xy-speed-mps) xy_speed="${2:?missing speed}"; shift 2 ;;
    --theta-speed-deg-s) theta_speed="${2:?missing speed}"; shift 2 ;;
    --camera-width) camera_width="${2:?missing width}"; shift 2 ;;
    --camera-height) camera_height="${2:?missing height}"; shift 2 ;;
    --camera-fps) camera_fps="${2:?missing fps}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }

# The recorder owns a small post-warmup window. Stop wheel input a little
# earlier so no base command can outlive its RGB-D recording.
base_runtime=$((duration - 3))
(( base_runtime >= 1 )) || base_runtime=1

ready_file="/tmp/forestbridge-slam-mapping-ready.json"
rm -f "$ready_file"
odom_pid=""

cleanup() {
  if [[ -n "$odom_pid" ]] && kill -0 "$odom_pid" 2>/dev/null; then
    kill -INT "$odom_pid" 2>/dev/null || true
    wait "$odom_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[1/4] Read-only Gemini gimbal reference check (no torque write)."
python3 tools/gemini_gimbal_pose.py \
  --reference "$gimbal_reference" check --tolerance-deg 1.0

echo "[2/4] Validating candidate base_link -> camera_link transform."
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live

cat <<EOF
[3/4] First mapping route: static 3 s -> forward about 0.5 m -> static 3 s
      -> reverse about 0.5 m -> static 3 s. If VO remains stable, continue
      at the same low speed around a small 1–2 m closed loop.

Camera, mapping and the base will be owned by this single session for ${duration}s.
Keep Gemini fixed. Space stops immediately; X/Esc ends base input; 12 V cutoff
remains the physical emergency stop. The process saves rtabmap.db and metrics.
EOF
read -r -p "Clear the entire route and hold the 12 V cutoff. Type MAP to start: " answer
[[ "$answer" == "MAP" ]] || { echo "Cancelled before camera or base torque was enabled."; exit 2; }

echo "[4/4] Starting ROS mapping graph; base torque remains off until its own BASE prompt."
bash scripts/slam_static_odom_container.sh \
  --mode mapping --transform-config "$config" --duration "$duration" \
  --camera-width "$camera_width" --camera-height "$camera_height" --camera-fps "$camera_fps" \
  --output-root /data/slam/mapping --ready-file "$ready_file" &
odom_pid=$!

deadline=$((SECONDS + 70))
while [[ ! -e "$ready_file" ]]; do
  if ! kill -0 "$odom_pid" 2>/dev/null; then
    wait "$odom_pid"
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for post-warmup recording; base torque was never enabled." >&2
    exit 1
  fi
  sleep 0.2
done

echo "Recording window is live. Do not press W/S yet: first type BASE and Enter at the next prompt."
python3 tools/base_keyboard.py --terminal \
  --xy-speed-mps "$xy_speed" --theta-speed-deg-s "$theta_speed" \
  --max-runtime-s "$base_runtime"

echo "Base input ended; waiting for the mapping recorder to finalize its artifacts."
wait "$odom_pid"
odom_pid=""
echo "PASS supervised mapping session. Inspect the printed /data/slam/mapping timestamp directory."
