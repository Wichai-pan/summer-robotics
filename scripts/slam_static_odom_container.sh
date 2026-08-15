#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
set -u

output_root="/data/slam/static-odom"
duration=60
dry_run=false
mode="static"
transform_config=""
localization_db=""
nav2_goal_x=""
nav2_goal_y=""
nav2_goal_yaw_deg="0"
nav2_params="configs/nav2/planning_dry_run.yaml"
nav2_robot_radius_m="0.30"
nav2_supervised_execute=false
nav2_execute_max_path_m="0.30"
nav2_execute_max_runtime_s="20"
nav2_execute_max_linear_mps="0.04"
nav2_execute_max_angular_deg_s="12"
nav2_execute_max_tracked_travel_m="0.40"
ready_file=""
camera_width=0
camera_height=0
camera_fps=0

usage() {
  cat <<'EOF'
Usage: slam_static_odom_container.sh [--duration SECONDS] [--output-root PATH] [--dry-run]
                                     [--mode static|motion|mapping|localization] [--transform-config PATH]
                                     [--localization-db PATH]
                                     [--nav2-goal-x M --nav2-goal-y M] [--nav2-goal-yaw-deg DEG]
                                     [--nav2-params PATH] [--nav2-robot-radius-m M]
                                     [--nav2-supervised-execute]
                                     [--nav2-execute-max-path-m M] [--nav2-execute-max-runtime-s S]
                                     [--nav2-execute-max-linear-mps MPS] [--nav2-execute-max-angular-deg-s DEG_S]
                                     [--nav2-execute-max-tracked-travel-m M]
                                     [--ready-file PATH] [--camera-width PX]
                                     [--camera-height PX] [--camera-fps HZ]

Runs Gemini-only RTAB-Map RGB-D odometry and writes compact JSONL plus a
quality report. In localization mode it loads an existing RTAB-Map database
read-only and validates map -> base_link; it does not open a motor device.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  --duration) duration="${2:?missing value for --duration}"; shift 2 ;;
  --output-root) output_root="${2:?missing value for --output-root}"; shift 2 ;;
  --mode) mode="${2:?missing value for --mode}"; shift 2 ;;
  --transform-config) transform_config="${2:?missing value for --transform-config}"; shift 2 ;;
  --localization-db) localization_db="${2:?missing value for --localization-db}"; shift 2 ;;
  --nav2-goal-x) nav2_goal_x="${2:?missing goal x}"; shift 2 ;;
  --nav2-goal-y) nav2_goal_y="${2:?missing goal y}"; shift 2 ;;
  --nav2-goal-yaw-deg) nav2_goal_yaw_deg="${2:?missing goal yaw}"; shift 2 ;;
  --nav2-params) nav2_params="${2:?missing Nav2 params path}"; shift 2 ;;
  --nav2-robot-radius-m) nav2_robot_radius_m="${2:?missing robot radius}"; shift 2 ;;
  --nav2-supervised-execute) nav2_supervised_execute=true; shift ;;
  --nav2-execute-max-path-m) nav2_execute_max_path_m="${2:?missing path cap}"; shift 2 ;;
  --nav2-execute-max-runtime-s) nav2_execute_max_runtime_s="${2:?missing runtime cap}"; shift 2 ;;
  --nav2-execute-max-linear-mps) nav2_execute_max_linear_mps="${2:?missing linear cap}"; shift 2 ;;
  --nav2-execute-max-angular-deg-s) nav2_execute_max_angular_deg_s="${2:?missing angular cap}"; shift 2 ;;
  --nav2-execute-max-tracked-travel-m) nav2_execute_max_tracked_travel_m="${2:?missing tracked travel cap}"; shift 2 ;;
  --ready-file) ready_file="${2:?missing value for --ready-file}"; shift 2 ;;
  --camera-width) camera_width="${2:?missing value for --camera-width}"; shift 2 ;;
  --camera-height) camera_height="${2:?missing value for --camera-height}"; shift 2 ;;
  --camera-fps) camera_fps="${2:?missing value for --camera-fps}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$duration" =~ ^[1-9][0-9]*$ ]] || {
  echo "--duration must be a positive integer" >&2
  exit 2
}
for camera_value in "$camera_width" "$camera_height" "$camera_fps"; do
  [[ "$camera_value" =~ ^[0-9]+$ ]] || {
    echo "camera width, height and fps must be non-negative integers" >&2
    exit 2
  }
done
if [[ "$camera_width" == 0 || "$camera_height" == 0 || "$camera_fps" == 0 ]]; then
  [[ "$camera_width" == 0 && "$camera_height" == 0 && "$camera_fps" == 0 ]] || {
    echo "camera width, height and fps must be all zero (device default) or all positive" >&2
    exit 2
  }
fi
[[ "$mode" == "static" || "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ]] || {
  echo "--mode must be static, motion, mapping or localization" >&2
  exit 2
}
if [[ ( "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ) && -z "$transform_config" ]]; then
  echo "--transform-config is required for motion/mapping/localization mode" >&2
  exit 2
fi
if [[ "$mode" == "localization" ]]; then
  [[ -n "$localization_db" ]] || { echo "--localization-db is required for localization mode" >&2; exit 2; }
  [[ -s "$localization_db" ]] || { echo "localization database is missing or empty: $localization_db" >&2; exit 2; }
fi
if [[ -n "$nav2_goal_x" || -n "$nav2_goal_y" ]]; then
  [[ "$mode" == "localization" ]] || { echo "Nav2 planning is only supported in localization mode" >&2; exit 2; }
  [[ -n "$nav2_goal_x" && -n "$nav2_goal_y" ]] || { echo "--nav2-goal-x and --nav2-goal-y must be supplied together" >&2; exit 2; }
  [[ -s "$nav2_params" ]] || { echo "Nav2 params file is missing or empty: $nav2_params" >&2; exit 2; }
fi
if [[ "$nav2_supervised_execute" == true && -z "$nav2_goal_x" ]]; then
  echo "--nav2-supervised-execute requires a Nav2 goal" >&2
  exit 2
fi

frame_id="camera_link"
metrics_tool="tools/slam_static_odom_metrics.py"
if [[ "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ]]; then
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

camera_command=(
  ros2 launch orbbec_camera gemini_330_series.launch.py
  enable_color:=true
  enable_depth:=true
  color_width:="$camera_width"
  color_height:="$camera_height"
  color_fps:="$camera_fps"
  depth_width:="$camera_width"
  depth_height:="$camera_height"
  depth_fps:="$camera_fps"
  depth_registration:=true
  align_mode:=SW
  align_target_stream:=COLOR
  enable_frame_sync:=true
  enable_point_cloud:=false
  enable_colored_point_cloud:=false
  enable_accel:=false
  enable_gyro:=false
  enable_sync_output_accel_gyro:=false
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
  if [[ "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ]]; then
    python3 tools/slam_base_camera_transform.py validate --config "$transform_config"
  fi
  python3 tools/capture_static_odom.py --duration "$duration" --dry-run
  python3 "$metrics_tool" --help >/dev/null
  python3 tools/slam_ros_graph_contract.py --help >/dev/null
  printf 'ODOM COMMAND:'
  printf ' %q' "${odom_command[@]}"
  printf '\n'
  printf 'CAMERA COMMAND:'
  printf ' %q' "${camera_command[@]}"
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
  if [[ "$mode" == "mapping" || "$mode" == "localization" ]]; then
    mapping_probe_log="$(mktemp)"
    mapping_probe_command=(
      ros2 run rtabmap_slam rtabmap --ros-args \
        -p frame_id:=base_link -p odom_frame_id:=odom -p map_frame_id:=map \
        -p 'RGBD/CreateOccupancyGrid:="true"' \
        -p 'Grid/FromDepth:="true"' \
        -p database_path:="${localization_db:-/tmp/rtabmap-smoke.db}"
    )
    if [[ "$mode" == "localization" ]]; then
      mapping_probe_command+=(
        -p 'Mem/IncrementalMemory:="false"' \
        -p 'Mem/InitWMWithAllNodes:="true"' \
        -p 'Mem/LocalizationReadOnly:="true"'
      )
    fi
    set +e
    # During a no-camera probe RTAB-Map can still be constructing ROS services
    # when SIGINT arrives. For localization the database is explicitly
    # read-only, so use SIGKILL after parameter parsing instead of turning that
    # shutdown race into a false configuration failure.
    if [[ "$mode" == "localization" ]]; then
      timeout --signal=KILL 3 "${mapping_probe_command[@]}" >"$mapping_probe_log" 2>&1
    else
      timeout --signal=INT --kill-after=1 3 "${mapping_probe_command[@]}" >"$mapping_probe_log" 2>&1
    fi
    mapping_probe_status=$?
    set -e
    if [[ "$mode" == "localization" ]]; then
      [[ $mapping_probe_status -eq 137 || $mapping_probe_status -eq 124 ]] || {
        cat "$mapping_probe_log" >&2
        rm -f "$mapping_probe_log"
        exit "$mapping_probe_status"
      }
    elif [[ $mapping_probe_status -ne 124 && $mapping_probe_status -ne 130 ]]; then
      cat "$mapping_probe_log" >&2
      rm -f "$mapping_probe_log"
      exit "$mapping_probe_status"
    fi
    if grep -Eqi 'UnknownROSArgsError|invalid parameter' "$mapping_probe_log"; then
      cat "$mapping_probe_log" >&2
      rm -f "$mapping_probe_log"
      exit 1
    fi
    rm -f "$mapping_probe_log"
  fi
  if [[ "$mode" == "localization" ]]; then
    echo "PASS localization configuration dry-run; no camera or motor device was opened"
  else
    echo "PASS $mode odometry dry-run; no camera or motor device was opened"
  fi
  exit 0
fi

if [[ "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ]]; then
  # Do not rely on readarray/process-substitution exit propagation below.
  python3 tools/slam_base_camera_transform.py validate \
    --config "$transform_config" --require-live
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_dir="$output_root/$stamp"
mkdir -p "$output_dir"

camera_log="$output_dir/orbbec-camera.log"
odom_log="$output_dir/rtabmap-rgbd-odometry.log"
mapping_log="$output_dir/rtabmap-mapping.log"
database_path="$output_dir/rtabmap.db"
if [[ "$mode" == "localization" ]]; then
  database_path="$localization_db"
fi
samples_file="$output_dir/$mode-odom.jsonl"
report_file="$output_dir/$mode-odom-report.json"
process_pids=()
printf '%s\n' \
  "{\"status\":\"INCOMPLETE\",\"failures\":[\"$mode odometry run did not finalize\"]}" \
  >"$report_file"
printf 'width=%s\nheight=%s\nfps=%s\npoint_cloud=false\n' \
  "$camera_width" "$camera_height" "$camera_fps" \
  >"$output_dir/camera-profile.txt"

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
  if [[ "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ]]; then
    graph_options+=(--allow-static-transform-publisher)
  fi
  if [[ "$mode" == "mapping" || "$mode" == "localization" ]]; then
    graph_options+=(--allow-rtabmap-mapping-tf-publisher)
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

capture_graph_contract_with_retry() {
  local suffix="$1"
  local attempt
  for attempt in 1 2 3; do
    if capture_graph_contract "$suffix"; then
      return 0
    fi
    echo "ROS graph contract attempt $attempt/3 failed; retrying discovery." >&2
    sleep 2
  done
  return 1
}

if [[ "$mode" == "motion" || "$mode" == "mapping" || "$mode" == "localization" ]]; then
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

setsid "${camera_command[@]}" >"$camera_log" 2>&1 &
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

if [[ "$mode" == "mapping" || "$mode" == "localization" ]]; then
  mapping_command=(
    ros2 run rtabmap_slam rtabmap
    --ros-args
    -r __ns:=/rtabmap
    -r rgb/image:=/camera/color/image_raw
    -r depth/image:=/camera/depth/image_raw
    -r rgb/camera_info:=/camera/color/camera_info
    -r odom:=/rtabmap/odom
    -r odom_info:=/rtabmap/odom_info
    -p frame_id:=base_link
    -p odom_frame_id:=odom
    -p map_frame_id:=map
    -p subscribe_odom_info:=true
    -p approx_sync:=true
    -p approx_sync_max_interval:=0.01
    -p topic_queue_size:=30
    -p sync_queue_size:=30
    -p qos:=1
    -p qos_camera_info:=1
    -p subscribe_rgbd:=false
    # RTAB-Map's internal parameters are strings, even for boolean concepts.
    # Keep the explicit inner quotes so ROS 2 does not coerce them to bool.
    -p 'RGBD/CreateOccupancyGrid:="true"'
    -p 'Grid/FromDepth:="true"'
    -p database_path:="$database_path"
  )
  if [[ "$mode" == "localization" ]]; then
    # Load the map without adding nodes or changing the saved database. This
    # is the required gate before Nav2 planning, not autonomous navigation.
    mapping_command+=(
      -p 'Mem/IncrementalMemory:="false"'
      -p 'Mem/InitWMWithAllNodes:="true"'
      -p 'Mem/LocalizationReadOnly:="true"'
    )
  fi
  setsid "${mapping_command[@]}" >"$mapping_log" 2>&1 &
  mapping_pid=$!
  process_pids+=("$mapping_pid")
  sleep 5
  kill -0 "$mapping_pid" || {
    echo "RTAB-Map mapping process exited during startup" >&2
    tail -n 100 "$mapping_log" >&2
    exit 1
  }
fi
ros2 node list | sort -u >"$output_dir/nodes.txt"
timeout 10 ros2 topic echo --once /tf >"$output_dir/tf-sample.txt"
timeout 10 ros2 topic echo --once /tf_static >"$output_dir/tf-static-sample.txt"
capture_graph_contract_with_retry ""

capture_args=(
  --warmup 2
  --duration "$duration"
  --output "$samples_file"
)
if [[ -n "$ready_file" ]]; then
  capture_args+=(--ready-file "$ready_file")
fi
set +e
python3 tools/capture_static_odom.py "${capture_args[@]}"
capture_status=$?
set -e

capture_graph_contract_with_retry "-post"
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

if [[ "$mode" == "mapping" ]]; then
  # RTAB-Map flushes its SQLite database on a graceful shutdown. Finalize it
  # before declaring the run successful instead of merely observing a file
  # that may still be open by the mapper.
  stop_process_group "$mapping_pid"
  sleep 1
fi

if [[ "$mode" == "localization" ]]; then
  localization_tf_file="$output_dir/tf-map-base-link.txt"
  set +e
  timeout --signal=INT --kill-after=1 15 \
    ros2 run tf2_ros tf2_echo map base_link >"$localization_tf_file" 2>&1
  localization_tf_status=$?
  set -e
  if [[ $localization_tf_status -ne 124 && $localization_tf_status -ne 130 ]]; then
    cat "$localization_tf_file" >&2
    echo "localization did not publish map -> base_link" >&2
    exit 1
  fi
  python3 - "$localization_tf_file" "$output_dir/localization-result.json" "$database_path" <<'PY'
import json
import sys
from pathlib import Path
from slam_ros_graph_contract import parse_tf_chain

source = Path(sys.argv[1])
target = Path(sys.argv[2])
try:
    transform = parse_tf_chain(source.read_text(encoding="utf-8"))
except ValueError as exc:
    raise SystemExit(f"localization did not produce a valid map -> base_link transform: {exc}")
payload = {"status": "PASS", "database_path": sys.argv[3], "map_to_base_link": transform}
target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2))
PY
  export_dir="$output_dir/occupancy-map"
  mkdir -p "$export_dir"
  rtabmap-export --map --opt 2 --output map --output_dir "$export_dir" "$database_path"
  python3 tools/render_localization_overlay.py \
    --map-pgm "$export_dir/map.pgm" \
    --map-yaml "$export_dir/map.yaml" \
    --pose-json "$output_dir/localization-result.json" \
    --output "$output_dir/localization-overlay.ppm"

  if [[ -n "$nav2_goal_x" ]]; then
    nav2_map_log="$output_dir/nav2-map-server.log"
    nav2_planner_log="$output_dir/nav2-planner-server.log"
    nav2_lifecycle_log="$output_dir/nav2-lifecycle-manager.log"
    nav2_path_file="$output_dir/nav2-path.json"
    nav2_map_command=(
      ros2 run nav2_map_server map_server
      --ros-args -r __node:=map_server
      -p yaml_filename:="$export_dir/map.yaml"
    )
    nav2_planner_command=(
      ros2 run nav2_planner planner_server
      --ros-args -r __node:=planner_server
      --params-file "$nav2_params"
      -p global_costmap.global_costmap.ros__parameters.robot_radius:="$nav2_robot_radius_m"
    )
    nav2_lifecycle_command=(
      ros2 run nav2_lifecycle_manager lifecycle_manager
      --ros-args -r __node:=lifecycle_manager
      --params-file "$nav2_params"
    )
    setsid "${nav2_map_command[@]}" >"$nav2_map_log" 2>&1 &
    nav2_map_pid=$!
    process_pids+=("$nav2_map_pid")
    setsid "${nav2_planner_command[@]}" >"$nav2_planner_log" 2>&1 &
    nav2_planner_pid=$!
    process_pids+=("$nav2_planner_pid")
    setsid "${nav2_lifecycle_command[@]}" >"$nav2_lifecycle_log" 2>&1 &
    nav2_lifecycle_pid=$!
    process_pids+=("$nav2_lifecycle_pid")

    nav2_deadline=$((SECONDS + 45))
    until ros2 action list 2>/dev/null | grep -Fxq /compute_path_to_pose; do
      if ! kill -0 "$nav2_map_pid" 2>/dev/null || ! kill -0 "$nav2_planner_pid" 2>/dev/null || ! kill -0 "$nav2_lifecycle_pid" 2>/dev/null; then
        echo "Nav2 planning process exited during startup" >&2
        tail -n 80 "$nav2_map_log" "$nav2_planner_log" "$nav2_lifecycle_log" >&2 || true
        exit 1
      fi
      if (( SECONDS >= nav2_deadline )); then
        echo "Timed out waiting for Nav2 ComputePathToPose action" >&2
        tail -n 80 "$nav2_map_log" "$nav2_planner_log" "$nav2_lifecycle_log" >&2 || true
        exit 1
      fi
      sleep 1
    done
    python3 tools/nav2_compute_path_dry_run.py \
      --goal-x "$nav2_goal_x" --goal-y "$nav2_goal_y" --goal-yaw-deg "$nav2_goal_yaw_deg" \
      --output "$nav2_path_file"
    python3 tools/render_localization_overlay.py \
      --map-pgm "$export_dir/map.pgm" \
      --map-yaml "$export_dir/map.yaml" \
      --pose-json "$output_dir/localization-result.json" \
      --path-json "$nav2_path_file" \
      --output "$output_dir/nav2-plan-overlay.ppm"
    if [[ "$nav2_supervised_execute" == true ]]; then
      echo "Nav2 path is ready. The next prompt is the only point that can enable base wheel torque."
      python3 tools/nav2_supervised_base_execute.py \
        --path-json "$nav2_path_file" \
        --output "$output_dir/nav2-execution-report.json" \
        --max-planned-path-m "$nav2_execute_max_path_m" \
        --max-runtime-s "$nav2_execute_max_runtime_s" \
        --max-linear-mps "$nav2_execute_max_linear_mps" \
        --max-angular-deg-s "$nav2_execute_max_angular_deg_s" \
        --max-tracked-travel-m "$nav2_execute_max_tracked_travel_m"
    fi
  fi
fi

if [[ "$mode" == "mapping" && ! -s "$database_path" ]]; then
  echo "FAIL mapping database was not created: $database_path" >&2
  exit 1
fi

printf 'PASS %s RGB-D odometry\nArtifacts: %s\n' "$mode" "$output_dir"
if [[ "$mode" == "mapping" ]]; then
  printf 'RTAB-Map database: %s\n' "$database_path"
fi
