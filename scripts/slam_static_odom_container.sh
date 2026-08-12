#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
set -u

output_root="/data/slam/static-odom"
duration=60
dry_run=false
mode="static"
transform_config=""

usage() {
  cat <<'EOF'
Usage: slam_static_odom_container.sh [--duration SECONDS] [--output-root PATH] [--dry-run]
                                     [--mode static|motion] [--transform-config PATH]

Runs Gemini-only RTAB-Map RGB-D odometry in camera_link and writes compact
JSONL plus a drift/quality report. It does not open a motor device.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  --duration) duration="${2:?missing value for --duration}"; shift 2 ;;
  --output-root) output_root="${2:?missing value for --output-root}"; shift 2 ;;
  --mode) mode="${2:?missing value for --mode}"; shift 2 ;;
  --transform-config) transform_config="${2:?missing value for --transform-config}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration" =~ ^[1-9][0-9]*$ ]] || {
  echo "--duration must be a positive integer" >&2
  exit 2
}
[[ "$mode" == "static" || "$mode" == "motion" ]] || {
  echo "--mode must be static or motion" >&2
  exit 2
}
if [[ "$mode" == "motion" && -z "$transform_config" ]]; then
  echo "--transform-config is required for motion mode" >&2
  exit 2
fi

frame_id="camera_link"
metrics_tool="tools/slam_static_odom_metrics.py"
if [[ "$mode" == "motion" ]]; then
  frame_id="base_link"
  metrics_tool="tools/slam_motion_odom_metrics.py"
fi

odom_command=(
  ros2 run rtabmap_odom rgbd_odometry
  --ros-args
  -r __ns:=/rtabmap
  -r rgb/image:=/camera/color/image_raw
  -r depth/image:=/camera/depth/image_raw
  -r rgb/camera_info:=/camera/color/camera_info
  -p frame_id:="$frame_id"
  -p odom_frame_id:=odom
  -p publish_tf:=true
  -p publish_null_when_lost:=true
  -p wait_for_transform:=0.2
  -p approx_sync:=true
  -p approx_sync_max_interval:=0.01
  -p topic_queue_size:=30
  -p sync_queue_size:=30
  -p qos:=1
  -p qos_camera_info:=1
  -p subscribe_rgbd:=false
  -p always_process_most_recent_frame:=true
)

if [[ "$dry_run" == true ]]; then
  ros2 pkg prefix rtabmap_odom >/dev/null
  ros2 pkg prefix tf2_ros >/dev/null
  interface_probe="$(mktemp)"
  ros2 interface show rtabmap_msgs/msg/OdomInfo >"$interface_probe"
  for required_field in \
    '^std_msgs/Header header' \
    '^bool lost' \
    '^int32 matches' \
    '^int32 inliers' \
    '^int32 features' \
    '^float32 time_estimation' \
    '^float32 interval'; do
    grep -q "$required_field" "$interface_probe"
  done
  rm -f "$interface_probe"
  if [[ "$mode" == "motion" ]]; then
    python3 tools/slam_base_camera_transform.py validate --config "$transform_config"
  fi
  python3 tools/capture_static_odom.py --duration "$duration" --dry-run
  python3 "$metrics_tool" --help >/dev/null
  python3 tools/slam_ros_graph_contract.py --help >/dev/null
  printf 'ODOM COMMAND:'
  printf ' %q' "${odom_command[@]}"
  printf '\n'

  probe_log="$(mktemp)"
  set +e
  timeout --signal=INT --kill-after=1 3 "${odom_command[@]}" >"$probe_log" 2>&1
  probe_status=$?
  set -e
  if [[ $probe_status -ne 124 && $probe_status -ne 130 ]]; then
    cat "$probe_log" >&2
    rm -f "$probe_log"
    exit "$probe_status"
  fi
  if grep -Eqi 'UnknownROSArgsError|invalid parameter|terminate called|exception' "$probe_log"; then
    cat "$probe_log" >&2
    rm -f "$probe_log"
    exit 1
  fi
  rm -f "$probe_log"
  echo "PASS $mode odometry dry-run; no camera or motor device was opened"
  exit 0
fi

if [[ "$mode" == "motion" ]]; then
  # Do not rely on readarray/process-substitution exit propagation below.
  python3 tools/slam_base_camera_transform.py validate \
    --config "$transform_config" --require-live
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_dir="$output_root/$stamp"
mkdir -p "$output_dir"

camera_log="$output_dir/orbbec-camera.log"
odom_log="$output_dir/rtabmap-rgbd-odometry.log"
samples_file="$output_dir/$mode-odom.jsonl"
report_file="$output_dir/$mode-odom-report.json"
process_pids=()
printf '%s\n' \
  "{\"status\":\"INCOMPLETE\",\"failures\":[\"$mode odometry run did not finalize\"]}" \
  >"$report_file"

stop_process_group() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 0
  kill -INT -- "-$pid" 2>/dev/null || true
  for _ in {1..10}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    sleep 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  local index
  for ((index=${#process_pids[@]}-1; index>=0; index--)); do
    stop_process_group "${process_pids[index]}"
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for_topics() {
  local owner_pid="$1"
  local log_file="$2"
  shift 2
  local topics=("$@")
  local topic
  local missing=("${topics[@]}")
  local deadline=$((SECONDS + 45))
  while (( SECONDS < deadline )); do
    ros2 topic list >"$output_dir/topics.txt" 2>/dev/null || true
    missing=()
    for topic in "${topics[@]}"; do
      grep -Fxq "$topic" "$output_dir/topics.txt" || missing+=("$topic")
    done
    (( ${#missing[@]} == 0 )) && return 0
    kill -0 "$owner_pid" 2>/dev/null || {
      echo "Process exited before required topics appeared" >&2
      tail -n 100 "$log_file" >&2
      return 1
    }
    sleep 1
  done
  printf 'Missing required topic: %s\n' "${missing[@]}" >&2
  tail -n 100 "$log_file" >&2
  return 1
}

capture_graph_contract() {
  local suffix="$1"
  local odom_info_file="$output_dir/odom-topic-info${suffix}.txt"
  local quality_info_file="$output_dir/odom-info-topic-info${suffix}.txt"
  local tf_info_file="$output_dir/tf-topic-info${suffix}.txt"
  local tf_static_info_file="$output_dir/tf-static-topic-info${suffix}.txt"
  local tf_chain_file="$output_dir/tf-odom-${frame_id//_/-}${suffix}.txt"
  local contract_file="$output_dir/ros-graph-contract${suffix}.json"
  local tf_status
  local graph_options=(--expected-child-frame "$frame_id")
  if [[ "$mode" == "motion" ]]; then
    graph_options+=(--allow-static-transform-publisher)
  fi

  ros2 topic info --verbose /rtabmap/odom >"$odom_info_file"
  ros2 topic info --verbose /rtabmap/odom_info >"$quality_info_file"
  ros2 topic info --verbose /tf >"$tf_info_file"
  ros2 topic info --verbose /tf_static >"$tf_static_info_file"

  set +e
  timeout --signal=INT --kill-after=1 5 \
    ros2 run tf2_ros tf2_echo odom "$frame_id" \
    >"$tf_chain_file" 2>&1
  tf_status=$?
  set -e
  if [[ $tf_status -ne 124 && $tf_status -ne 130 ]]; then
    cat "$tf_chain_file" >&2
    echo "tf2_echo exited unexpectedly with status $tf_status" >&2
    return 1
  fi

  python3 tools/slam_ros_graph_contract.py \
    --odom-topic-info "$odom_info_file" \
    --odom-info-topic-info "$quality_info_file" \
    --tf-topic-info "$tf_info_file" \
    --tf-static-topic-info "$tf_static_info_file" \
    --tf-chain "$tf_chain_file" \
    "${graph_options[@]}" \
    --output "$contract_file"
}

if [[ "$mode" == "motion" ]]; then
  readarray -t transform_args < <(
    python3 tools/slam_base_camera_transform.py static-transform-args \
      --config "$transform_config" --require-live
  )
  setsid ros2 run tf2_ros static_transform_publisher "${transform_args[@]}" \
    --ros-args -r __node:=base_to_gemini_static_tf \
    >"$output_dir/base-to-gemini-static-tf.log" 2>&1 &
  transform_pid=$!
  process_pids+=("$transform_pid")
fi

setsid ros2 launch orbbec_camera gemini_330_series.launch.py \
  enable_color:=true \
  enable_depth:=true \
  depth_registration:=true \
  align_mode:=SW \
  align_target_stream:=COLOR \
  enable_frame_sync:=true \
  enable_accel:=false \
  enable_gyro:=false \
  enable_sync_output_accel_gyro:=false \
  >"$camera_log" 2>&1 &
camera_pid=$!
process_pids+=("$camera_pid")

wait_for_topics "$camera_pid" "$camera_log" \
  /camera/color/image_raw \
  /camera/color/camera_info \
  /camera/depth/image_raw \
  /tf_static

setsid "${odom_command[@]}" >"$odom_log" 2>&1 &
odom_pid=$!
process_pids+=("$odom_pid")

wait_for_topics "$odom_pid" "$odom_log" /rtabmap/odom /rtabmap/odom_info
ros2 node list | sort -u >"$output_dir/nodes.txt"
timeout 10 ros2 topic echo --once /tf >"$output_dir/tf-sample.txt"
timeout 10 ros2 topic echo --once /tf_static >"$output_dir/tf-static-sample.txt"
capture_graph_contract ""

set +e
python3 tools/capture_static_odom.py \
  --warmup 2 \
  --duration "$duration" \
  --output "$samples_file"
capture_status=$?
set -e

capture_graph_contract "-post"
kill -0 "$camera_pid"
kill -0 "$odom_pid"
minimum_duration=$(((duration * 8 + 9) / 10))
upstream_failure=()
if [[ $capture_status -ne 0 ]]; then
  upstream_failure=(--upstream-failure "capture exited with status $capture_status")
fi
set +e
python3 "$metrics_tool" "$samples_file" \
  --output "$report_file" \
  --minimum-duration-s "$minimum_duration" \
  "${upstream_failure[@]}"
analysis_status=$?
set -e

if [[ $capture_status -ne 0 || $analysis_status -ne 0 ]]; then
  echo "FAIL $mode RGB-D odometry; see $report_file" >&2
  exit 1
fi

printf 'PASS %s RGB-D odometry\nArtifacts: %s\n' "$mode" "$output_dir"
