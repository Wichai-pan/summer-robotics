#!/usr/bin/env bash
set -euo pipefail

if (($# != 2)); then
  echo "Usage: $0 FROM_POSE_ID TO_POSE_ID" >&2
  echo "Example: $0 right_c.predock_pose right_a.predock_pose" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace_config="$repo_root/configs/nav2/home_workspaces_20260902T194820Z.yaml"
map_timestamp="${JETSON_HOME_MAP_TIMESTAMP:-20260902T194820Z}"

read -r start_x start_y start_yaw < <(
  python3 "$repo_root/tools/resolve_home_workspace_pose.py" \
    --config "$workspace_config" --pose-id "$1" --tsv
)
read -r goal_x goal_y goal_yaw < <(
  python3 "$repo_root/tools/resolve_home_workspace_pose.py" \
    --config "$workspace_config" --pose-id "$2" --tsv
)

echo "连续导航：$1 -> $2"
echo "起点连续性检查：($start_x, $start_y, $start_yaw deg)"
echo "终点：($goal_x, $goal_y, $goal_yaw deg)"
echo "路径上限 3.00 m，累计行程上限 3.25 m，运行上限 180 s。"
echo "急停：立即断开 12 V，或运行 scripts/jetson_home_navigation_stop.sh。"

goal_mode_args=()
wheel_visual_policy="guarded"
from_workspace="${1%%.*}"
to_workspace="${2%%.*}"
from_pose_kind="${1#*.}"
to_pose_kind="${2#*.}"

# A predock/work pair in the same workspace is a short, nearly collinear
# furniture approach.  Do not use the ordinary path follower here: it points
# the chassis along Nav2's intermediate path headings, which turns a simple
# forward/reverse move into rotate-drive-rotate.  Enter docking mode from the
# first control cycle, align the recorded destination yaw, then translate in
# the map frame with the omni base while holding that yaw.
if [[ "$from_workspace" == "$to_workspace" ]] &&
   { [[ "$from_pose_kind" == "predock_pose" && "$to_pose_kind" == "work_pose" ]] ||
     [[ "$from_pose_kind" == "work_pose" && "$to_pose_kind" == "predock_pose" ]]; }; then
  goal_mode_args+=(
    --dock-entry-distance-m 0.50
    --dock-yaw-align-tolerance-deg 2
    --dock-yaw-realign-tolerance-deg 5
  )
  echo "同工作区直移模式：先对准目标航向，再保持航向全向平移。"
  wheel_visual_policy="bounded"
fi

if [[ "$to_pose_kind" == "work_pose" ]]; then
  # Work poses intentionally overlap height-separated furniture in the 2-D
  # map, so retain the validated exact endpoint after NavFn's safe endpoint.
  goal_mode_args+=(--append-exact-goal)
fi

exec bash "$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh" \
  --database "/workspace/artifacts/slam/${map_timestamp}/navigation-work/rtabmap-candidate-working.db" \
  --goal-x "$goal_x" --goal-y "$goal_y" --goal-yaw-deg "$goal_yaw" \
  --expected-start-x "$start_x" --expected-start-y "$start_y" --expected-start-yaw-deg "$start_yaw" \
  --duration 30 --robot-radius-m 0.30 \
  --max-path-m 3.00 --max-runtime-s 180 --max-tracked-travel-m 3.25 \
  --control-pose-source wheel --wheel-visual-policy "$wheel_visual_policy" \
  --position-tolerance-m 0.03 --yaw-tolerance-deg 2 \
  "${goal_mode_args[@]}"
