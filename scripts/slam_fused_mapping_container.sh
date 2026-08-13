#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/humble/setup.bash

mode="mapping"
database_path="${FORESTBRIDGE_SLAM_DATABASE:-/data/slam/fused/rtabmap.db}"
if [[ "${1:-}" == "--mode" ]]; then
  mode="${2:-}"
fi
[[ "$mode" == "mapping" || "$mode" == "localization" ]] || {
  echo "mode must be mapping or localization" >&2
  exit 2
}

transform_config="configs/slam/base_to_gemini_candidate.yaml"
feedback_config="configs/slam/sts3215_wheel_feedback_unresolved.json"
imu_config="configs/slam/gemini_imu_unresolved.json"
python3 tools/slam_base_camera_transform.py validate --config "$transform_config" --require-live
python3 tools/base_wheel_feedback.py --config "$feedback_config" --validate-live
python3 tools/slam_imu_contract.py --require-live --config "$imu_config" \
  --ekf-config configs/slam/ekf_fused_odom.yaml

if [[ ! -t 0 ]]; then
  echo "fused mapping control requires an interactive TTY" >&2
  exit 2
fi
read -r -p "Area clear, immediate 12V cutoff ready. Type FUSED to enable base control: " answer
[[ "$answer" == "FUSED" ]] || { echo "cancelled before motor access"; exit 2; }

mkdir -p "$(dirname "$database_path")"
if [[ "$mode" == "mapping" && -e "$database_path" ]]; then
  echo "mapping database already exists; choose a new FORESTBRIDGE_SLAM_DATABASE" >&2
  exit 2
fi
if [[ "$mode" == "localization" && ! -f "$database_path" ]]; then
  echo "localization database does not exist: $database_path" >&2
  exit 2
fi

pids=()
monitor_pid=""
cleanup() {
  local pid
  [[ -z "$monitor_pid" ]] || kill "$monitor_pid" 2>/dev/null || true
  for pid in "${pids[@]}"; do
    kill -INT -- "-$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "${pids[@]}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Unreachable until feedback units pass the read-only pilot. Kept here so the
# future one-container process and TF ownership can be reviewed now.
readarray -t tf_args < <(python3 tools/slam_base_camera_transform.py static-transform-args \
  --config "$transform_config" --require-live)
setsid ros2 run tf2_ros static_transform_publisher "${tf_args[@]}" \
  --ros-args -r __node:=base_to_gemini_static_tf &
pids+=("$!")

setsid ros2 launch orbbec_camera gemini_330_series.launch.py \
  enable_color:=true enable_depth:=true depth_registration:=true \
  align_mode:=SW align_target_stream:=COLOR enable_frame_sync:=true \
  enable_accel:=true enable_gyro:=true enable_sync_output_accel_gyro:=true &
pids+=("$!")

imu_sample="/tmp/forestbridge-gemini-imu-sample.txt"
deadline=$((SECONDS + 45))
until ros2 topic list 2>/dev/null | grep -Fxq /camera/gyro_accel/sample; do
  (( SECONDS < deadline )) || { echo "Gemini IMU topic did not appear" >&2; exit 1; }
  kill -0 "${pids[1]}" 2>/dev/null || { echo "Gemini camera exited" >&2; exit 1; }
  sleep 1
done
[[ "$(ros2 topic type /camera/gyro_accel/sample)" == "sensor_msgs/msg/Imu" ]] || {
  echo "Gemini IMU type mismatch" >&2
  exit 1
}
timeout 10 ros2 topic echo --once /camera/gyro_accel/sample >"$imu_sample"
grep -q 'frame_id: camera_accel_gyro_optical_frame' "$imu_sample"
grep -A1 'orientation_covariance:' "$imu_sample" | grep -q -- '- -1.0'

setsid python3 tools/base_odometry_ros.py --live --enable-control --confirmed \
  --config "$feedback_config" &
pids+=("$!")
setsid ros2 run robot_localization ekf_node --ros-args \
  --params-file configs/slam/ekf_fused_odom.yaml \
  -r odometry/filtered:=/odom &
pids+=("$!")

incremental=true
init_all=false
[[ "$mode" == "localization" ]] && incremental=false && init_all=true
setsid ros2 run rtabmap_slam rtabmap --ros-args \
  -r rgb/image:=/camera/color/image_raw \
  -r depth/image:=/camera/depth/image_raw \
  -r rgb/camera_info:=/camera/color/camera_info \
  -r odom:=/odom \
  -p frame_id:=base_link -p 'odom_frame_id:=' -p map_frame_id:=map \
  -p database_path:="$database_path" \
  -p subscribe_rgb:=true -p subscribe_depth:=true -p approx_sync:=true \
  -p publish_tf:=true -p "Mem/IncrementalMemory:=$incremental" \
  -p "Mem/InitWMWithAllNodes:=$init_all" &
rtabmap_pid=$!
pids+=("$rtabmap_pid")

# Keep the only TTY reader in the foreground. A side monitor terminates this
# parent shell if any required backend exits, which triggers the cleanup trap.
parent_pid=$$
(
  while true; do
    for pid in "${pids[@]}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "required fused-SLAM process $pid exited" >&2
        kill -TERM "$parent_pid"
        exit 0
      fi
    done
    sleep 0.2
  done
) &
monitor_pid=$!
set +e
python3 tools/base_keyboard_ros.py --live \
  --deadman-ms 250 --xy-speed-mps 0.04 --theta-speed-deg-s 12 \
  --max-runtime-s 120
keyboard_status=$?
set -e
kill "$monitor_pid" 2>/dev/null || true
wait "$monitor_pid" 2>/dev/null || true
exit "$keyboard_status"
