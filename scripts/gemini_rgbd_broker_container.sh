#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
set -u

shared_dir="${FORESTBRIDGE_GEMINI_SHARED_DIR:-/dev/shm/forestbridge-gemini}"
ready_file="${FORESTBRIDGE_GEMINI_BROKER_READY:-/data/runtime/forestbridge-gemini-broker.ready}"
camera_log="${FORESTBRIDGE_GEMINI_CAMERA_LOG:-/data/runtime/forestbridge-gemini-broker-camera.log}"
bridge_log="${FORESTBRIDGE_GEMINI_BRIDGE_LOG:-/data/runtime/forestbridge-gemini-broker-bridge.log}"
camera_pid=""
bridge_pid=""

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  rm -f "$ready_file"
  for pid in "$bridge_pid" "$camera_pid"; do
    [[ -n "$pid" ]] || continue
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "$bridge_pid" "$camera_pid"; do
    [[ -n "$pid" ]] || continue
    kill -KILL -- "-$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$(dirname "$ready_file")" "$shared_dir"
rm -f "$ready_file"

setsid ros2 launch orbbec_camera gemini_330_series.launch.py \
  enable_color:=true \
  enable_depth:=true \
  color_width:=640 \
  color_height:=480 \
  color_fps:=30 \
  depth_width:=640 \
  depth_height:=480 \
  depth_fps:=30 \
  depth_registration:=true \
  align_mode:=SW \
  align_target_stream:=COLOR \
  enable_frame_sync:=true \
  enable_point_cloud:=false \
  enable_colored_point_cloud:=false \
  enable_accel:=false \
  enable_gyro:=false \
  enable_sync_output_accel_gyro:=false \
  >"$camera_log" 2>&1 &
camera_pid=$!

deadline=$((SECONDS + 30))
while ((SECONDS < deadline)); do
  kill -0 "$camera_pid" 2>/dev/null || {
    tail -80 "$camera_log" >&2 || true
    exit 1
  }
  topics="$(ros2 topic list 2>/dev/null || true)"
  if grep -Fxq /camera/color/image_raw <<<"$topics" && \
     grep -Fxq /camera/depth/image_raw <<<"$topics" && \
     grep -Fxq /camera/color/camera_info <<<"$topics"; then
    break
  fi
  sleep 0.5
done

topics="$(ros2 topic list 2>/dev/null || true)"
for topic in /camera/color/image_raw /camera/depth/image_raw /camera/color/camera_info; do
  grep -Fxq "$topic" <<<"$topics" || {
    echo "Gemini broker topic did not appear: $topic" >&2
    tail -80 "$camera_log" >&2 || true
    exit 1
  }
done

setsid env PYTHONPATH=/data/services/forestbridge-gemini-broker:/workspace/tools:${PYTHONPATH:-} \
  python3 /data/services/forestbridge-gemini-broker/ros_image_task_preview.py \
  --topic /camera/color/image_raw \
  --shared-frame-dir "$shared_dir" \
  --shared-max-hz 10 \
  >"$bridge_log" 2>&1 &
bridge_pid=$!

deadline=$((SECONDS + 10))
while ((SECONDS < deadline)); do
  kill -0 "$bridge_pid" 2>/dev/null || {
    tail -80 "$bridge_log" >&2 || true
    exit 1
  }
  [[ -s "$shared_dir/latest.jpg" && -s "$shared_dir/latest.json" ]] && break
  sleep 0.2
done
[[ -s "$shared_dir/latest.jpg" && -s "$shared_dir/latest.json" ]] || {
  echo "Gemini broker did not publish a shared RGB frame" >&2
  tail -80 "$bridge_log" >&2 || true
  exit 1
}

printf '%s\n' "pid=$$" "shared_dir=$shared_dir" "ros_domain_id=${ROS_DOMAIN_ID:-}" >"$ready_file"
echo "Gemini RGB-D broker ready: ROS topics + $shared_dir"

wait -n "$camera_pid" "$bridge_pid"
echo "Gemini RGB-D broker component exited unexpectedly" >&2
exit 1
