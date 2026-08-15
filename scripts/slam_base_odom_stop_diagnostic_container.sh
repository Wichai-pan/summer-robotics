#!/usr/bin/env bash
set -euo pipefail

# Compare one physically observable forward pulse with RGB-D odometry while a
# single container owns Gemini, gimbal readback, and the white base serial bus.
# It never loads a map, Nav2, or an arm controller.

duration=16
command_s=1.0
linear_mps=0.04
config="configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml"
gimbal_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"

usage() {
  cat <<'EOF'
Usage: slam_base_odom_stop_diagnostic_container.sh [--duration S] [--command-s S]
       [--linear-mps MPS] [--config PATH] [--gimbal-reference PATH]

Records fixed-Gemini RGB-D odometry while issuing exactly one original Nav2
forward pulse, followed by torque-on zero-velocity braking and torque release.
Mark the initial and final chassis position with tape and measure the physical
displacement after the run. This is a scale/stop diagnostic, not navigation.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) duration="${2:?missing duration}"; shift 2 ;;
    --command-s) command_s="${2:?missing command duration}"; shift 2 ;;
    --linear-mps) linear_mps="${2:?missing linear speed}"; shift 2 ;;
    --config) config="${2:?missing config}"; shift 2 ;;
    --gimbal-reference) gimbal_reference="${2:?missing reference}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }
python3 - "$command_s" "$linear_mps" <<'PY'
import sys
command_s, linear_mps = map(float, sys.argv[1:])
if not 0.0 < command_s <= 2.0:
    raise SystemExit("--command-s must be in (0, 2.0]")
if not 0.0 < linear_mps <= 0.04:
    raise SystemExit("--linear-mps must be in (0, 0.04]")
PY
(( duration >= 14 )) || { echo "--duration must be at least 14s for a usable odometry report" >&2; exit 2; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_root="/data/slam/base-odom-stop/$stamp"
ready_file="$run_root/recording-ready.json"
wheel_report="$run_root/wheel-stop.json"
mkdir -p "$run_root"

odom_pid=""
cleanup() {
  if [[ -n "$odom_pid" ]] && kill -0 "$odom_pid" 2>/dev/null; then
    kill -INT "$odom_pid" 2>/dev/null || true
    wait "$odom_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[1/3] Read-only check: Gemini must stay at the saved mapping-down pose."
python3 tools/gemini_gimbal_pose.py \
  --reference "$gimbal_reference" check --tolerance-deg 1.0
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live

cat <<EOF
[2/3] Put a tape mark at the same chassis reference point before and after the run.
This will command one forward pulse: ${linear_mps} m/s for ${command_s}s, then active braking.
Keep the route clear and hold the 12 V cutoff. No map/Nav2/arm command is involved.
EOF
read -r -p "Type ODOM to start RGB-D recording: " answer
[[ "$answer" == "ODOM" ]] || { echo "Cancelled before camera or wheel torque."; exit 2; }

bash scripts/slam_static_odom_container.sh \
  --mode motion --transform-config "$config" --duration "$duration" \
  --output-root "$run_root" --ready-file "$ready_file" \
  --camera-width 640 --camera-height 480 --camera-fps 30 &
odom_pid=$!

deadline=$((SECONDS + 70))
while [[ ! -e "$ready_file" ]]; do
  if ! kill -0 "$odom_pid" 2>/dev/null; then
    wait "$odom_pid"
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out before RGB-D recording was ready; wheel torque was never enabled." >&2
    exit 1
  fi
  sleep 0.2
done

echo "[3/3] RGB-D recording is live. The next prompt is the only point that enables wheel torque."
python3 tools/base_stop_diagnostic.py \
  --linear-mps "$linear_mps" --command-s "$command_s" --output "$wheel_report"

echo "Wheel pulse ended; wait for RGB-D recorder to finalize."
wait "$odom_pid"
odom_pid=""
printf 'PASS base/RGB-D odometry pulse session. Root artifacts: %s\n' "$run_root"
printf 'Measure the tape displacement now; wheel telemetry: %s\n' "$wheel_report"
