#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_nav_then_act_pick_place.sh [options]

Run the supervised MVP sequence: fixed mapping gimbal -> Nav2 table docking ->
fixed ACT gimbal -> supervised ACT pick/place -> folded-arm recovery.

This is an orchestration wrapper only. It does not replace the standalone
mapping, Nav2, gimbal, or ACT scripts. Every existing physical-motion gate is
preserved: PIPELINE, RETURN, PLAN, MOVE, READY and the ACT result/return
prompts. Any failed stage stops the sequence before the next stage begins.

Options:
  --database PATH                 RTAB-Map database
  --mapping-reference PATH        fixed gimbal pose used by mapping/Nav2
  --grasp-reference PATH          fixed gimbal pose used by ACT
  --goal-x M --goal-y M           table docking goal in map coordinates
  --goal-yaw-deg DEG              final chassis heading in map coordinates
  --label NAME                    label recorded by the ACT trial log
  --steps N                       ACT rollout steps (20 Hz; 600 = 30 s)
  --duration S                    static RGB-D localization duration
  --robot-radius-m M              Nav2 robot radius
  --max-path-m M                  maximum planned route length
  --max-runtime-s S               Nav2 supervised motion time cap
  --max-tracked-travel-m M        Nav2 wheel-tracked travel cap
  --position-tolerance-m M        Nav2 final XY arrival tolerance
  --dock-entry-distance-m M       switch to holonomic table docking within M
  --dock-yaw-align-tolerance-deg D  yaw tolerance before/while docking
  --control-pose-source rgbd|wheel  Nav2 control pose source
  -h, --help                      show this message
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
database="/data/slam/mapping/20260825T131710Z/rtabmap.db"
mapping_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"
grasp_reference="/data/config/gemini_gimbal_grasp_pose_v1.json"
goal_x="0.052"
goal_y="-0.357"
goal_yaw_deg="-90"
label="nav_act_pick_place"
steps="600"
duration="20"
robot_radius_m="0.30"
max_path_m="1.20"
max_runtime_s="80"
max_tracked_travel_m="1.35"
position_tolerance_m="0.025"
dock_entry_distance_m="0.18"
dock_yaw_align_tolerance_deg="6"
control_pose_source="wheel"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database) database="${2:?missing value for --database}"; shift 2 ;;
    --mapping-reference) mapping_reference="${2:?missing value for --mapping-reference}"; shift 2 ;;
    --grasp-reference) grasp_reference="${2:?missing value for --grasp-reference}"; shift 2 ;;
    --goal-x) goal_x="${2:?missing value for --goal-x}"; shift 2 ;;
    --goal-y) goal_y="${2:?missing value for --goal-y}"; shift 2 ;;
    --goal-yaw-deg) goal_yaw_deg="${2:?missing value for --goal-yaw-deg}"; shift 2 ;;
    --label) label="${2:?missing value for --label}"; shift 2 ;;
    --steps) steps="${2:?missing value for --steps}"; shift 2 ;;
    --duration) duration="${2:?missing value for --duration}"; shift 2 ;;
    --robot-radius-m) robot_radius_m="${2:?missing value for --robot-radius-m}"; shift 2 ;;
    --max-path-m) max_path_m="${2:?missing value for --max-path-m}"; shift 2 ;;
    --max-runtime-s) max_runtime_s="${2:?missing value for --max-runtime-s}"; shift 2 ;;
    --max-tracked-travel-m) max_tracked_travel_m="${2:?missing value for --max-tracked-travel-m}"; shift 2 ;;
    --position-tolerance-m) position_tolerance_m="${2:?missing value for --position-tolerance-m}"; shift 2 ;;
    --dock-entry-distance-m) dock_entry_distance_m="${2:?missing value for --dock-entry-distance-m}"; shift 2 ;;
    --dock-yaw-align-tolerance-deg) dock_yaw_align_tolerance_deg="${2:?missing value for --dock-yaw-align-tolerance-deg}"; shift 2 ;;
    --control-pose-source) control_pose_source="${2:?missing value for --control-pose-source}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$steps" =~ ^[1-9][0-9]*$ ]] || { echo "--steps must be a positive integer" >&2; exit 2; }
case "$control_pose_source" in rgbd|wheel) ;; *) echo "--control-pose-source must be rgbd or wheel" >&2; exit 2 ;; esac

echo "Supervised Nav2 -> ACT pick/place pipeline"
echo "Map: $database"
echo "Dock goal: x=$goal_x m, y=$goal_y m, yaw=$goal_yaw_deg deg"
echo "ACT: $steps steps, label=$label"
echo "This does not transport an object after pickup; ACT performs its existing local pick/place rollout."
echo "Keep the 12 V cutoff available and clear the route, gimbal cables and arm workspace."
read -r -p "Type PIPELINE to begin the mapping-gimbal return: " pipeline
if [[ "$pipeline" != "PIPELINE" ]]; then
  echo "Pipeline cancelled before any motor command."
  exit 1
fi

cd "$repo_root"

echo "=== 1/4 RETURN GEMINI TO MAPPING REFERENCE ==="
"$repo_root/scripts/jetson_slam_exec.sh" \
  --black --interactive -- \
  python3 tools/gemini_gimbal_pose.py \
  --reference "$mapping_reference" \
  return --execute

echo "=== 2/4 NAVIGATE TO TABLE DOCKING POSE ==="
"$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh" \
  --database "$database" \
  --goal-x "$goal_x" \
  --goal-y "$goal_y" \
  --goal-yaw-deg "$goal_yaw_deg" \
  --duration "$duration" \
  --robot-radius-m "$robot_radius_m" \
  --max-path-m "$max_path_m" \
  --max-runtime-s "$max_runtime_s" \
  --max-tracked-travel-m "$max_tracked_travel_m" \
  --control-pose-source "$control_pose_source" \
  --dock-entry-distance-m "$dock_entry_distance_m" \
  --dock-yaw-align-tolerance-deg "$dock_yaw_align_tolerance_deg" \
  --position-tolerance-m "$position_tolerance_m"

echo "=== 3/4 RETURN GEMINI TO ACT GRASP REFERENCE ==="
"$repo_root/scripts/jetson_slam_exec.sh" \
  --black --interactive -- \
  python3 tools/gemini_gimbal_pose.py \
  --reference "$grasp_reference" \
  return --execute

echo "=== 4/4 RUN SUPERVISED ACT PICK/PLACE ==="
"$repo_root/scripts/jetson_act_trial.sh" \
  --label "$label" \
  --steps "$steps"
