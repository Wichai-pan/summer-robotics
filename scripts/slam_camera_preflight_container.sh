#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
set -u

output_root="${1:-/data/slam/preflight}"
record_seconds="${2:-10}"
[[ "$record_seconds" =~ ^[0-9]+$ ]] || {
  echo "record_seconds must be a non-negative integer" >&2
  exit 2
}
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_dir="$output_root/$stamp"
mkdir -p "$output_dir"

camera_log="$output_dir/orbbec-camera.log"
topics_file="$output_dir/topics.txt"
camera_pid=""

cleanup() {
  [[ -n "$camera_pid" ]] || return 0
  kill -0 "$camera_pid" 2>/dev/null || return 0
  kill -INT -- "-$camera_pid" 2>/dev/null || true
  for _ in {1..10}; do
    kill -0 "$camera_pid" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "$camera_pid" 2>/dev/null; then
    kill -TERM -- "-$camera_pid" 2>/dev/null || true
    sleep 1
  fi
  if kill -0 "$camera_pid" 2>/dev/null; then
    kill -KILL -- "-$camera_pid" 2>/dev/null || true
  fi
  wait "$camera_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

setsid ros2 launch orbbec_camera gemini_330_series.launch.py \
  enable_color:=true \
  enable_depth:=true \
  depth_registration:=true \
  align_mode:=SW \
  align_target_stream:=COLOR \
  enable_frame_sync:=true \
  enable_accel:=true \
  enable_gyro:=true \
  enable_sync_output_accel_gyro:=true \
  >"$camera_log" 2>&1 &
camera_pid=$!

required_topics=(
  /camera/color/image_raw
  /camera/color/camera_info
  /camera/depth/image_raw
  /camera/depth/camera_info
  /camera/gyro_accel/sample
  /tf_static
)

deadline=$((SECONDS + 45))
while (( SECONDS < deadline )); do
  ros2 topic list >"$topics_file" 2>/dev/null || true
  missing=()
  for topic in "${required_topics[@]}"; do
    grep -Fxq "$topic" "$topics_file" || missing+=("$topic")
  done
  (( ${#missing[@]} == 0 )) && break
  kill -0 "$camera_pid" 2>/dev/null || {
    echo "Orbbec node exited before required topics appeared" >&2
    tail -n 80 "$camera_log" >&2
    exit 1
  }
  sleep 1
done

if (( ${#missing[@]} != 0 )); then
  printf 'Missing required topic: %s\n' "${missing[@]}" >&2
  tail -n 80 "$camera_log" >&2
  exit 1
fi

for topic in "${required_topics[@]}"; do
  safe_name="${topic//\//_}"
  timeout 15 ros2 topic echo --once "$topic" >"$output_dir/${safe_name}.txt"
done

ros2 node list | sort -u >"$output_dir/nodes.txt"
for topic in /camera/color/image_raw /camera/depth/image_raw; do
  safe_name="${topic//\//_}"
  ros2 topic info --verbose "$topic" >"$output_dir/${safe_name}_info.txt"
  grep -q 'Publisher count: 1' "$output_dir/${safe_name}_info.txt"
done

ros2 param get /camera/camera enable_depth_scale \
  >"$output_dir/depth-scale-parameter.txt"
ros2 param get /camera/camera depth_precision \
  >>"$output_dir/depth-scale-parameter.txt"

capture_rate() {
  local topic="$1"
  local safe_name="${topic//\//_}"
  local status
  set +e
  timeout --signal=INT --kill-after=2 8 \
    ros2 topic hz --window 300 "$topic" \
    >"$output_dir/${safe_name}_hz.txt" 2>&1
  status=$?
  set -e
  if [[ $status -ne 0 && $status -ne 124 && $status -ne 130 ]]; then
    cat "$output_dir/${safe_name}_hz.txt" >&2
    return "$status"
  fi
  grep -q 'average rate:' "$output_dir/${safe_name}_hz.txt"
}

capture_rate /camera/color/image_raw
capture_rate /camera/depth/image_raw
capture_rate /camera/gyro_accel/sample

if (( record_seconds > 0 )); then
  set +e
  timeout --signal=INT --kill-after=5 "$record_seconds" \
    ros2 bag record --storage mcap --output "$output_dir/gemini-smoke" \
    "${required_topics[@]}" \
    >"$output_dir/rosbag-record.log" 2>&1
  bag_status=$?
  set -e
  if [[ $bag_status -ne 0 && $bag_status -ne 124 && $bag_status -ne 130 ]]; then
    cat "$output_dir/rosbag-record.log" >&2
    exit "$bag_status"
  fi

  ros2 bag info "$output_dir/gemini-smoke" >"$output_dir/rosbag-info.txt"
  grep -q '/camera/color/image_raw' "$output_dir/rosbag-info.txt"
  grep -q '/camera/depth/image_raw' "$output_dir/rosbag-info.txt"
  grep -q '/camera/gyro_accel/sample' "$output_dir/rosbag-info.txt"
  grep -q '/tf_static' "$output_dir/rosbag-info.txt"
fi

printf 'PASS Gemini ROS camera preflight\nArtifacts: %s\n' "$output_dir"
