#!/usr/bin/env bash
set -euo pipefail

mode="mapping"
dry_run=false
python_cmd="python3"
if ! python3 --version >/dev/null 2>&1; then
  python_cmd="python"
fi
for arg in "$@"; do
  case "$arg" in
    --mapping) mode="mapping" ;;
    --localization) mode="localization" ;;
    --dry-run) dry_run=true ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$dry_run" == true ]]; then
  "$python_cmd" tools/base_wheel_feedback.py --dry-run
  "$python_cmd" tools/base_odometry_ros.py --dry-run
  "$python_cmd" tools/slam_base_camera_transform.py validate \
    --config configs/slam/base_to_gemini_candidate.yaml
  "$python_cmd" tools/slam_fused_graph_contract.py \
    --config configs/slam/fused_slam_graph.json
  "$python_cmd" tools/slam_imu_contract.py \
    --config configs/slam/gemini_imu_unresolved.json \
    --ekf-config configs/slam/ekf_fused_odom.yaml
  echo "PASS fused SLAM dry-run ($mode); no Docker, lock, ROS, camera, or serial access"
  exit 0
fi

# This check intentionally runs before Docker or the shared hardware lock.
"$python_cmd" tools/base_wheel_feedback.py --config \
  configs/slam/sts3215_wheel_feedback_unresolved.json --validate-live
"$python_cmd" tools/slam_imu_contract.py --require-live \
  --config configs/slam/gemini_imu_unresolved.json \
  --ekf-config configs/slam/ekf_fused_odom.yaml

# Future live execution owns Gemini and the white board in one container/lock.
# The in-container reader is hard-whitelisted to wheel IDs 7/8/9.
exec ./scripts/jetson_slam_exec.sh --gemini --white --interactive -- \
  bash scripts/slam_fused_mapping_container.sh --mode "$mode"
