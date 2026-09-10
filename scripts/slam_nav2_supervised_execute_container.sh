#!/usr/bin/env bash
set -euo pipefail

database=""
goal_x=""
goal_y=""
goal_yaw_deg=0
route_file=""
workspace_config="configs/nav2/home_workspaces_20260902T194820Z.yaml"
duration=60
config="configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml"
gimbal_reference="/data/config/gemini_gimbal_mapping_down_20deg_v1.json"
robot_radius_m=0.30
max_path_m=0.30
max_runtime_s=20
max_tracked_travel_m=0.40
control_pose_source="rgbd"
wheel_visual_policy="bounded"
dock_entry_distance_m="0"
dock_yaw_align_tolerance_deg="6"
dock_yaw_realign_tolerance_deg="8"
position_tolerance_m="0.07"
yaw_tolerance_deg="8"
append_exact_goal=false
expected_start_x=""
expected_start_y=""
expected_start_yaw_deg=""
initial_map_pose_x=""
initial_map_pose_y=""
initial_map_pose_yaw_deg=""
expected_start_max_position_error_m="0.25"
expected_start_max_yaw_error_deg="25"
external_camera=false

usage() {
  cat <<'EOF'
Usage: slam_nav2_supervised_execute_container.sh --database PATH (--goal-x M --goal-y M | --route-file PATH)
       [--goal-yaw-deg DEG] [--duration S] [--config PATH]
       [--gimbal-reference PATH] [--robot-radius-m M] [--max-path-m M]
       [--max-runtime-s S] [--max-tracked-travel-m M] [--control-pose-source rgbd|wheel]
       [--wheel-visual-policy bounded|liveness]
       [--dock-entry-distance-m M] [--dock-yaw-align-tolerance-deg DEG]
       [--dock-yaw-realign-tolerance-deg DEG]
       [--position-tolerance-m M]
       [--yaw-tolerance-deg DEG]
       [--append-exact-goal]
       [--workspace-config PATH]
       [--expected-start-x M --expected-start-y M --expected-start-yaw-deg DEG]
       [--initial-map-pose-x M --initial-map-pose-y M --initial-map-pose-yaw-deg DEG]
       [--expected-start-max-position-error-m M --expected-start-max-yaw-error-deg DEG]
       [--external-camera]

First-motion navigation test only: localizes Gemini against a read-only RTAB-Map
database, asks Nav2 for a path, then requires a second MOVE confirmation before
opening the white base controller. Base motion is limited to 0.04 m/s and 12
deg/s. Any error actively brakes and checks all three torque registers before
releasing the serial port. White arm IDs 1-6 are never commanded. The
supervised path cap cannot exceed 3.00 m. Runtime cannot exceed 180 s.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database) database="${2:?missing database}"; shift 2 ;;
    --goal-x) goal_x="${2:?missing goal x}"; shift 2 ;;
    --goal-y) goal_y="${2:?missing goal y}"; shift 2 ;;
    --goal-yaw-deg) goal_yaw_deg="${2:?missing goal yaw}"; shift 2 ;;
    --route-file) route_file="${2:?missing route file}"; shift 2 ;;
    --workspace-config) workspace_config="${2:?missing workspace config}"; shift 2 ;;
    --duration) duration="${2:?missing duration}"; shift 2 ;;
    --config) config="${2:?missing config}"; shift 2 ;;
    --gimbal-reference) gimbal_reference="${2:?missing reference}"; shift 2 ;;
    --robot-radius-m) robot_radius_m="${2:?missing radius}"; shift 2 ;;
    --max-path-m) max_path_m="${2:?missing maximum path}"; shift 2 ;;
    --max-runtime-s) max_runtime_s="${2:?missing maximum runtime}"; shift 2 ;;
    --max-tracked-travel-m) max_tracked_travel_m="${2:?missing maximum travel}"; shift 2 ;;
    --control-pose-source) control_pose_source="${2:?missing control pose source}"; shift 2 ;;
    --wheel-visual-policy) wheel_visual_policy="${2:?missing wheel visual policy}"; shift 2 ;;
    --dock-entry-distance-m) dock_entry_distance_m="${2:?missing dock entry distance}"; shift 2 ;;
    --dock-yaw-align-tolerance-deg) dock_yaw_align_tolerance_deg="${2:?missing dock yaw tolerance}"; shift 2 ;;
    --dock-yaw-realign-tolerance-deg) dock_yaw_realign_tolerance_deg="${2:?missing dock re-align yaw tolerance}"; shift 2 ;;
    --position-tolerance-m) position_tolerance_m="${2:?missing position tolerance}"; shift 2 ;;
    --yaw-tolerance-deg) yaw_tolerance_deg="${2:?missing yaw tolerance}"; shift 2 ;;
    --append-exact-goal) append_exact_goal=true; shift ;;
    --expected-start-x) expected_start_x="${2:?missing expected x}"; shift 2 ;;
    --expected-start-y) expected_start_y="${2:?missing expected y}"; shift 2 ;;
    --expected-start-yaw-deg) expected_start_yaw_deg="${2:?missing expected yaw}"; shift 2 ;;
    --initial-map-pose-x) initial_map_pose_x="${2:?missing initial map x}"; shift 2 ;;
    --initial-map-pose-y) initial_map_pose_y="${2:?missing initial map y}"; shift 2 ;;
    --initial-map-pose-yaw-deg) initial_map_pose_yaw_deg="${2:?missing initial map yaw}"; shift 2 ;;
    --expected-start-max-position-error-m) expected_start_max_position_error_m="${2:?missing expected position gate}"; shift 2 ;;
    --expected-start-max-yaw-error-deg) expected_start_max_yaw_error_deg="${2:?missing expected yaw gate}"; shift 2 ;;
    --external-camera) external_camera=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$database" && -s "$database" ]] || { echo "a readable --database is required" >&2; exit 2; }
if [[ -n "$route_file" ]]; then
  [[ -z "$goal_x" && -z "$goal_y" ]] || { echo "use either --route-file or a single goal" >&2; exit 2; }
  [[ -s "$route_file" ]] || { echo "route file is missing or empty: $route_file" >&2; exit 2; }
  [[ -s "$workspace_config" ]] || { echo "workspace config is missing or empty: $workspace_config" >&2; exit 2; }
else
  [[ -n "$goal_x" && -n "$goal_y" ]] || { echo "--goal-x and --goal-y are required without --route-file" >&2; exit 2; }
fi
[[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "--duration must be a positive integer" >&2; exit 2; }
[[ "$control_pose_source" == "rgbd" || "$control_pose_source" == "wheel" ]] || {
  echo "--control-pose-source must be rgbd or wheel" >&2
  exit 2
}
[[ "$wheel_visual_policy" == "bounded" || "$wheel_visual_policy" == "guarded" || "$wheel_visual_policy" == "liveness" ]] || {
  echo "--wheel-visual-policy must be bounded, guarded or liveness" >&2
  exit 2
}
python3 - "$max_path_m" "$max_runtime_s" "$max_tracked_travel_m" <<'PY'
import sys
path_m, runtime_s, tracked_m = map(float, sys.argv[1:])
if not 0.0 < path_m <= 3.00:
    raise SystemExit("--max-path-m must be in (0, 3.00] for supervised motion")
if not 0.0 < runtime_s <= 180.0:
    raise SystemExit("--max-runtime-s must be in (0, 180] for supervised motion")
if not path_m < tracked_m <= 3.25:
    raise SystemExit("--max-tracked-travel-m must exceed --max-path-m and be <=3.25")
PY

echo "[1/3] Read-only Gemini gimbal reference check (no torque write)."
python3 tools/gemini_gimbal_pose.py --reference "$gimbal_reference" check --tolerance-deg 1.0
echo "[2/3] Validating fixed base_link -> camera_link transform."
python3 tools/slam_base_camera_transform.py validate --config "$config" --require-live
cat <<EOF
[3/3] Supervised first-motion test: RTAB-Map database remains read-only; Nav2
will plan first. The base stays torque-free until the later MOVE confirmation.
Safety caps: planned path <=${max_path_m} m; base <=0.04 m/s and <=12 deg/s;
${max_runtime_s} s max. Control pose=${control_pose_source}; wheel visual policy=${wheel_visual_policy}. Any stop must verify all three wheel torque registers.
EOF
if [[ "${FORESTBRIDGE_DEMO_ARMED:-0}" == "1" ]]; then
  echo "AUTO_PIPELINE armed; PLAN is automatically confirmed."
else
  read -r -p "Type PLAN to open Gemini, localize, and compute the short path: " answer
  [[ "$answer" == "PLAN" ]] || { echo "Cancelled before camera or base torque was enabled."; exit 2; }
fi

exact_goal_args=()
if [[ "$append_exact_goal" == true ]]; then
  exact_goal_args+=(--nav2-append-exact-goal)
fi
navigation_args=()
if [[ -n "$route_file" ]]; then
  navigation_args+=(--nav2-route-file "$route_file" --nav2-workspace-config "$workspace_config")
else
  navigation_args+=(--nav2-goal-x "$goal_x" --nav2-goal-y "$goal_y" --nav2-goal-yaw-deg "$goal_yaw_deg")
fi
expected_start_args=()
if [[ -n "$expected_start_x" || -n "$expected_start_y" || -n "$expected_start_yaw_deg" ]]; then
  [[ -n "$expected_start_x" && -n "$expected_start_y" && -n "$expected_start_yaw_deg" ]] || {
    echo "expected start pose requires x, y and yaw" >&2; exit 2;
  }
  expected_start_args+=(--expected-start-x "$expected_start_x" --expected-start-y "$expected_start_y" --expected-start-yaw-deg "$expected_start_yaw_deg")
  expected_start_args+=(--expected-start-max-position-error-m "$expected_start_max_position_error_m" --expected-start-max-yaw-error-deg "$expected_start_max_yaw_error_deg")
fi
initial_map_pose_args=()
if [[ -n "$initial_map_pose_x" || -n "$initial_map_pose_y" || -n "$initial_map_pose_yaw_deg" ]]; then
  [[ -n "$initial_map_pose_x" && -n "$initial_map_pose_y" && -n "$initial_map_pose_yaw_deg" ]] || {
    echo "initial map pose requires x, y and yaw" >&2; exit 2;
  }
  initial_map_pose_args+=(--initial-map-pose-x "$initial_map_pose_x" --initial-map-pose-y "$initial_map_pose_y" --initial-map-pose-yaw-deg "$initial_map_pose_yaw_deg")
fi
camera_source_args=()
if [[ "$external_camera" == true ]]; then
  camera_source_args+=(--external-camera)
fi
bash scripts/slam_static_odom_container.sh \
  --mode localization --localization-db "$database" --transform-config "$config" \
  --duration "$duration" --output-root /data/slam/nav2-supervised-execute \
  --camera-width 640 --camera-height 480 --camera-fps 30 \
  "${navigation_args[@]}" \
  --nav2-robot-radius-m "$robot_radius_m" \
  --nav2-supervised-execute \
  --nav2-execute-max-path-m "$max_path_m" \
  --nav2-execute-max-runtime-s "$max_runtime_s" \
  --nav2-execute-max-linear-mps 0.04 \
  --nav2-execute-max-angular-deg-s 12 \
  --nav2-execute-max-tracked-travel-m "$max_tracked_travel_m" \
  --nav2-execute-control-pose-source "$control_pose_source" \
  --nav2-execute-wheel-visual-policy "$wheel_visual_policy" \
  --nav2-execute-dock-entry-distance-m "$dock_entry_distance_m" \
  --nav2-execute-dock-yaw-align-tolerance-deg "$dock_yaw_align_tolerance_deg" \
  --nav2-execute-dock-yaw-realign-tolerance-deg "$dock_yaw_realign_tolerance_deg" \
  --nav2-execute-position-tolerance-m "$position_tolerance_m" \
  --nav2-execute-yaw-tolerance-deg "$yaw_tolerance_deg" \
  "${expected_start_args[@]}" \
  "${initial_map_pose_args[@]}" \
  "${exact_goal_args[@]}" \
  "${camera_source_args[@]}"

echo "PASS supervised Nav2 first-motion session. Inspect the printed /data/slam/nav2-supervised-execute timestamp directory."
