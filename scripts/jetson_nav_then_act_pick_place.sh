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
prompts. With --auto-demo, one AUTO_PIPELINE authorization replaces the inner
confirmations while all motion limits and failure stops remain active. Any
failed stage stops the sequence before the next stage begins.

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
  --auto-demo                     one initial AUTO_PIPELINE authorization; no inner prompts
  -h, --help                      show this message
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/forestbridge_task_guard.sh"
database="/data/slam/mapping/20260830T095346Z/rtabmap.db"
mapping_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"
grasp_reference="/data/config/gemini_gimbal_grasp_pose_v1.json"
goal_x="0.060"
goal_y="-0.372"
goal_yaw_deg="-90"
label="nav_act_pick_place"
steps="600"
duration="20"
robot_radius_m="0.30"
max_path_m="1.20"
max_runtime_s="80"
max_tracked_travel_m="1.35"
# The integrated table-docking demo accepts a 5 cm terminal XY envelope.  The
# standalone Nav2 entrypoint keeps its stricter default, and callers can still
# request a tighter pipeline tolerance explicitly.
position_tolerance_m="0.050"
dock_entry_distance_m="0.18"
dock_yaw_align_tolerance_deg="6"
control_pose_source="wheel"
auto_demo=false

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
    --auto-demo) auto_demo=true; shift ;;
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
pipeline_token="PIPELINE"
if $auto_demo; then
  pipeline_token="AUTO_PIPELINE"
  echo "AUTO DEMO: this single authorization permits gimbal motion, localization/planning, bounded base motion and ACT rollout."
  echo "No inner PLAN/MOVE/READY/ROLLOUT prompts will pause the task. The 12 V cutoff must remain attended."
fi
read -r -p "Type $pipeline_token to begin: " pipeline
if [[ "$pipeline" != "$pipeline_token" ]]; then
  echo "Pipeline cancelled before any motor command."
  exit 1
fi

if $auto_demo; then
  export FORESTBRIDGE_DEMO_ARMED=1
fi

cd "$repo_root"
trap forestbridge_task_guard_end EXIT
forestbridge_task_guard_begin

echo "=== 1/5 RETURN WHITE ARM TO FOLDED TRAVEL POSE ==="
"$repo_root/scripts/jetson_robot_exec.sh" \
  --white --interactive -- \
  python3 tools/return_white_to_folded_pose.py --execute

echo "=== 2/5 RETURN GEMINI TO MAPPING REFERENCE ==="
"$repo_root/scripts/jetson_slam_exec.sh" \
  --black --interactive -- \
  python3 tools/gemini_gimbal_pose.py \
  --reference "$mapping_reference" \
  return --execute

echo "=== 3/5 NAVIGATE TO TABLE DOCKING POSE ==="
bash "$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh" \
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

echo "=== 4/5 RETURN GEMINI TO ACT GRASP REFERENCE ==="
"$repo_root/scripts/jetson_slam_exec.sh" \
  --black --interactive -- \
  python3 tools/gemini_gimbal_pose.py \
  --reference "$grasp_reference" \
  return --execute

echo "=== 5/5 RUN SUPERVISED ACT PICK/PLACE ==="
bash "$repo_root/scripts/jetson_act_trial.sh" \
  --label "$label" \
  --steps "$steps" \
  --skip-return
