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

usage() {
  cat <<'EOF'
Usage: slam_nav2_planning_dry_run_container.sh --database PATH --goal-x M --goal-y M
       [--goal-yaw-deg DEG] [--duration S] [--config PATH]
       [--gimbal-reference PATH] [--robot-radius-m M]

Loads an RTAB-Map database read-only, localizes the live Gemini, then asks only
Nav2 planner_server for a path. No controller_server/BT navigator is started and
this process never maps a base serial device or publishes cmd_vel.
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
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$database" && -s "$database" ]] || { echo "a readable --database is required" >&2; exit 2; }
[[ -n "$goal_x" && -n "$goal_y" ]] || { echo "--goal-x and --goal-y are required" >&2; exit 2; }
[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }

echo "[1/3] Read-only Gemini gimbal reference check (no torque write)."
python3 tools/gemini_gimbal_pose.py --reference "$gimbal_reference" check --tolerance-deg 1.0
echo "[2/3] Validating fixed base_link -> camera_link transform."
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live
cat <<EOF
[3/3] Planner-only session: map database is read-only; Gemini localizes, then
Nav2 computes a path to map goal (${goal_x}, ${goal_y}). No base device,
controller_server, BT navigator or /cmd_vel publisher exists in this session.
EOF
read -r -p "Type PLAN to open Gemini and compute the dry-run path: " answer
[[ "$answer" == "PLAN" ]] || { echo "Cancelled before Gemini was opened."; exit 2; }

bash scripts/slam_static_odom_container.sh \
  --mode localization --localization-db "$database" --transform-config "$config" \
  --duration "$duration" --output-root /data/slam/nav2-dry-run \
  --camera-width 640 --camera-height 480 --camera-fps 30 \
  --nav2-goal-x "$goal_x" --nav2-goal-y "$goal_y" --nav2-goal-yaw-deg "$goal_yaw_deg" \
  --nav2-robot-radius-m "$robot_radius_m"

echo "PASS Nav2 planning-only session. Inspect the printed /data/slam/nav2-dry-run timestamp directory."
