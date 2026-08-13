#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_act_trial.sh [--label NAME] [--steps N] [--checkpoint PATH]
                           [--dataset-root PATH] [--skip-return]
                           [--skip-final-return]

Run one supervised white-arm ACT pick/place trial on Jetson.  By default the
script first runs the folded-pose return, pauses for the operator to reset the
scene, runs ACT with the control rates used during recording, then requests a
separate supervised return after the operator labels the outcome.

Every invocation writes a new timestamped log below
/home/jetsonl7/robot-data/logs and updates act_rollout_latest.log.
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
log_dir="${FORESTBRIDGE_ACT_LOG_DIR:-$data_root/logs}"
label="repeat"
steps=600
checkpoint="${FORESTBRIDGE_ACT_CHECKPOINT:-/data/models/act_fixed_pick_place_v2_28ep_616995_006000}"
dataset_root="${FORESTBRIDGE_ACT_DATASET_ROOT:-/data/act/fixed_pick_place_v1}"
return_first=true
return_final=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) label="${2:?missing value for --label}"; shift 2 ;;
    --steps) steps="${2:?missing value for --steps}"; shift 2 ;;
    --checkpoint) checkpoint="${2:?missing value for --checkpoint}"; shift 2 ;;
    --dataset-root) dataset_root="${2:?missing value for --dataset-root}"; shift 2 ;;
    --skip-return) return_first=false; shift ;;
    --skip-final-return) return_final=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$steps" =~ ^[1-9][0-9]*$ ]] || { echo "--steps must be a positive integer" >&2; exit 2; }
safe_label="${label//[^A-Za-z0-9._-]/_}"
timestamp="$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$log_dir"
log_path="$log_dir/${timestamp}_${safe_label}.log"
latest_path="$log_dir/act_rollout_latest.log"

finish() {
  ln -sfn "$log_path" "$latest_path"
  printf '\nLog saved: %s\nLatest link: %s\n' "$log_path" "$latest_path"
}
trap finish EXIT

run_logged() {
  set +e
  "$@" 2>&1 | tee -a "$log_path"
  local command_status="${PIPESTATUS[0]}"
  set -e
  return "$command_status"
}

cd "$repo_root"
{
  echo "FORESTBRIDGE_ACT_TRIAL"
  echo "timestamp=$timestamp"
  echo "label=$label"
  echo "steps=$steps"
  echo "duration_s=$((steps / 20))"
  echo "checkpoint=$checkpoint"
  echo "dataset_root=$dataset_root"
  echo "git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
} | tee "$log_path"

if $return_first; then
  echo | tee -a "$log_path"
  echo "=== RETURN TO FOLDED POSE ===" | tee -a "$log_path"
  run_logged \
    "$repo_root/scripts/jetson_robot_exec.sh" \
    --white --interactive -- \
    python3 tools/return_white_to_folded_pose.py --execute
fi

echo
echo "Reset the face-cream jar, cameras, lighting and workspace for this trial."
read -r -p "Type READY when the fixed scene is ready: " ready
if [[ "$ready" != "READY" ]]; then
  echo "Trial cancelled before ACT; no policy motion was sent." | tee -a "$log_path"
  exit 1
fi

echo | tee -a "$log_path"
echo "=== ACT ROLLOUT ===" | tee -a "$log_path"
run_logged \
  "$repo_root/scripts/jetson_robot_exec.sh" \
  --gemini --wrist-a --white --interactive -- \
  python3 tools/act_white_short_rollout.py \
  --checkpoint "$checkpoint" \
  --dataset-root "$dataset_root" \
  --steps "$steps" \
  --max-arm-step-deg 1.5 \
  --max-gripper-step 3 \
  --max-total-arm-travel-deg 100 \
  --max-total-elbow-travel-deg 130 \
  --max-total-gripper-travel 60 \
  --grasp-supervisor \
  --execute

echo
read -r -p "Result (SUCCESS/PARTIAL/FAIL/UNKNOWN): " result
case "$result" in
  SUCCESS|PARTIAL|FAIL|UNKNOWN) ;;
  *) result="UNKNOWN" ;;
esac
read -r -p "Short operator note (optional): " operator_note
{
  echo
  echo "EXPERIMENT_RESULT=$result"
  echo "OPERATOR_NOTE=$operator_note"
} | tee -a "$log_path"

if $return_final; then
  echo | tee -a "$log_path"
  echo "=== FINAL RETURN TO FOLDED POSE ===" | tee -a "$log_path"
  echo "Clear the white-arm return path; type RETURN in the next prompt to recover." | tee -a "$log_path"
  run_logged \
    "$repo_root/scripts/jetson_robot_exec.sh" \
    --white --interactive -- \
    python3 tools/return_white_to_folded_pose.py --execute
fi
