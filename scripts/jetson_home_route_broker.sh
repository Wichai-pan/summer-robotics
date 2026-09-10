#!/usr/bin/env bash
set -euo pipefail

if (($# != 1)) || [[ "$1" != "table-to-sofa" && "$1" != "sofa-to-table" ]]; then
  echo "Usage: $0 table-to-sofa|sofa-to-table" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
map_timestamp="${JETSON_HOME_MAP_TIMESTAMP:-20260902T194820Z}"
workspace_config="configs/nav2/home_workspaces_20260902T194820Z.yaml"

if [[ "$1" == "table-to-sofa" ]]; then
  route_file="configs/nav2/table_to_sofa_continuous_20260902T194820Z.yaml"
  start_pose="right_a.work_pose"
  description="桌面工作位 -> 桌前准备位 -> 沙发前准备位 -> 沙发工作位"
else
  route_file="configs/nav2/sofa_to_table_continuous_20260902T194820Z.yaml"
  start_pose="right_c.work_pose"
  description="沙发工作位 -> 沙发准备位 -> 桌前准备位 -> 桌面工作位"
fi

read -r start_x start_y start_yaw < <(
  python3 "$repo_root/tools/resolve_home_workspace_pose.py" \
    --config "$repo_root/$workspace_config" --pose-id "$start_pose" --tsv
)

echo "Broker 连续路线：$description"
echo "Gemini 由常驻 RGB-D broker 共享；此任务不会重新打开相机。"

exec bash "$repo_root/scripts/jetson_slam_nav2_broker_execute.sh" \
  --database "/workspace/artifacts/slam/${map_timestamp}/navigation-work/rtabmap-candidate-working.db" \
  --route-file "$route_file" --workspace-config "$workspace_config" \
  --expected-start-x "$start_x" --expected-start-y "$start_y" --expected-start-yaw-deg "$start_yaw" \
  --initial-map-pose-x "$start_x" --initial-map-pose-y "$start_y" --initial-map-pose-yaw-deg "$start_yaw" \
  --expected-start-max-position-error-m 0.25 --expected-start-max-yaw-error-deg 25 \
  --duration 30 --robot-radius-m 0.30 \
  --max-path-m 3.00 --max-runtime-s 180 --max-tracked-travel-m 3.25 \
  --control-pose-source wheel \
  --dock-yaw-align-tolerance-deg 2 --dock-yaw-realign-tolerance-deg 5 \
  --position-tolerance-m 0.03 --yaw-tolerance-deg 2
