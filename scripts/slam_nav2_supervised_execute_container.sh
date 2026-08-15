#!/usr/bin/env bash
set -euo pipefail

database=""
goal_x=""
goal_y=""
goal_yaw_deg=0
duration=60
config="configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml"
gimbal_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"
robot_radius_m=0.30
max_path_m=0.30
max_runtime_s=20
max_tracked_travel_m=0.40

usage() {
  cat <<'EOF'
Usage: slam_nav2_supervised_execute_container.sh --database PATH --goal-x M --goal-y M
       [--goal-yaw-deg DEG] [--duration S] [--config PATH]
       [--gimbal-reference PATH] [--robot-radius-m M] [--max-path-m M]
       [--max-runtime-s S] [--max-tracked-travel-m M]

First-motion navigation test only: localizes Gemini against a read-only RTAB-Map
database, asks Nav2 for a path, then requires a second MOVE confirmation before
opening the white base controller. Base motion is limited to 0.04 m/s and 12
deg/s. Any error actively brakes and checks all three torque registers before
releasing the serial port. White arm IDs 1-6 are never commanded. The
supervised path cap cannot exceed 1.10 m.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database) database="${2:?missing database}"; shift 2 ;;
    --goal-x) goal_x="${2:?missing goal x}"; shift 2 ;;
    --goal-y) goal_y="${2:?missing goal y}"; shift 2 ;;
    --goal-yaw-deg) goal_yaw_deg="${2:?missing goal yaw}"; shift 2 ;;
    --duration) duration="${2:?missing duration}"; shift 2 ;;
    --config) config="${2:?missing config}"; shift 2 ;;
    --gimbal-reference) gimbal_reference="${2:?missing reference}"; shift 2 ;;
    --robot-radius-m) robot_radius_m="${2:?missing radius}"; shift 2 ;;
    --max-path-m) max_path_m="${2:?missing maximum path}"; shift 2 ;;
    --max-runtime-s) max_runtime_s="${2:?missing maximum runtime}"; shift 2 ;;
    --max-tracked-travel-m) max_tracked_travel_m="${2:?missing maximum travel}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$database" && -s "$database" ]] || { echo "a readable --database is required" >&2; exit 2; }
[[ -n "$goal_x" && -n "$goal_y" ]] || { echo "--goal-x and --goal-y are required" >&2; exit 2; }
[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }
python3 - "$max_path_m" "$max_runtime_s" "$max_tracked_travel_m" <<'PY'
import sys
path_m, runtime_s, tracked_m = map(float, sys.argv[1:])
if not 0.0 < path_m <= 1.10:
    raise SystemExit("--max-path-m must be in (0, 1.10] for supervised motion")
if not 0.0 < runtime_s <= 35.0:
    raise SystemExit("--max-runtime-s must be in (0, 35] for supervised motion")
if not path_m < tracked_m <= 1.25:
    raise SystemExit("--max-tracked-travel-m must exceed --max-path-m and be <=1.25")
PY

echo "[1/3] Read-only Gemini gimbal reference check (no torque write)."
python3 tools/gemini_gimbal_pose.py --reference "$gimbal_reference" check --tolerance-deg 1.0
echo "[2/3] Validating fixed base_link -> camera_link transform."
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live
cat <<EOF
[3/3] Supervised first-motion test: RTAB-Map database remains read-only; Nav2
will plan first. The base stays torque-free until the later MOVE confirmation.
Safety caps: planned path <=${max_path_m} m; base <=0.04 m/s and <=12 deg/s;
${max_runtime_s} s max. Any stop must verify all three wheel torque registers.
EOF
read -r -p "Type PLAN to open Gemini, localize, and compute the short path: " answer
[[ "$answer" == "PLAN" ]] || { echo "Cancelled before camera or base torque was enabled."; exit 2; }

bash scripts/slam_static_odom_container.sh \
  --mode localization --localization-db "$database" --transform-config "$config" \
  --duration "$duration" --output-root /data/slam/nav2-supervised-execute \
  --camera-width 640 --camera-height 480 --camera-fps 30 \
  --nav2-goal-x "$goal_x" --nav2-goal-y "$goal_y" --nav2-goal-yaw-deg "$goal_yaw_deg" \
  --nav2-robot-radius-m "$robot_radius_m" \
  --nav2-supervised-execute \
  --nav2-execute-max-path-m "$max_path_m" \
  --nav2-execute-max-runtime-s "$max_runtime_s" \
  --nav2-execute-max-linear-mps 0.04 \
  --nav2-execute-max-angular-deg-s 12 \
  --nav2-execute-max-tracked-travel-m "$max_tracked_travel_m"

echo "PASS supervised Nav2 first-motion session. Inspect the printed /data/slam/nav2-supervised-execute timestamp directory."
