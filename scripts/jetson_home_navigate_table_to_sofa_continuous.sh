#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
map_timestamp="${JETSON_HOME_MAP_TIMESTAMP:-20260902T194820Z}"
workspace_config="configs/nav2/home_workspaces_20260902T194820Z.yaml"
route_file="configs/nav2/table_to_sofa_continuous_20260902T194820Z.yaml"

read -r start_x start_y start_yaw < <(
  python3 "$repo_root/tools/resolve_home_workspace_pose.py" \
    --config "$repo_root/$workspace_config" --pose-id right_a.work_pose --tsv
)

cat <<EOF
连续路线：桌面工作位 -> 桌前准备位 -> 沙发前准备位 -> 沙发工作位
只在开始进行一次 30 秒桌面区域定位检查；后续路线保持同一 RTAB-Map、TF 和 Nav2 栈。
跨区到达沙发准备位后进行 30 秒静止定位，按新位置微调准备位，再进入沙发工作位。
进入沙发工作位后再次进行 30 秒静止定位，按新位置完成最终修正和严格验收。
每一段单独规划且上限 3.00 m；段末主动制动、关闭三轮扭矩并回读三次。
家具区采用先对准目标航向、再保持航向全向平移；跨区只用轮式里程计控制并采用全向路径跟随，Gemini 仅检查数据流存活。
EOF

exec bash "$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh" \
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
