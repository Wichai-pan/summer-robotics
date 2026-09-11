#!/usr/bin/env bash
set -euo pipefail

# Fixed-scene web entry point for the teammate's 60-episode red measuring-cup
# ACT pick policy. Gemini comes from the persistent broker; this script never
# opens the physical Gemini device itself.

if [[ "${1:-}" != "--execute" ]]; then
  echo "Usage: $0 --execute --steps N" >&2
  exit 2
fi
shift
steps=""
if [[ "${1:-}" == "--steps" && -n "${2:-}" ]]; then
  steps="$2"
  shift 2
fi
[[ -n "$steps" && "$steps" =~ ^[0-9]+$ ]] || {
  echo "--steps must be a positive integer" >&2
  exit 2
}
[[ $# -eq 0 ]] || { echo "Unknown argument: $1" >&2; exit 2; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
shared_dir="${FORESTBRIDGE_GEMINI_SHARED_DIR:-/dev/shm/forestbridge-gemini}"
[[ -s "$shared_dir/latest.jpg" && -s "$shared_dir/latest.json" ]] || {
  echo "Persistent Gemini broker is not ready." >&2
  exit 3
}

echo "=== 1/2 RETURN WHITE ARM TO SMALL-CUP START POSE ==="
"$repo_root/scripts/jetson_robot_exec.sh" \
  --white --interactive -- \
  python3 tools/return_white_to_folded_pose.py \
    --folded-pose-json /data/act/config/white_empty_folded_pose_v2.json \
    --timeout-s 60 \
    --execute

echo "=== 2/2 RUN FIXED-WORKSPACE SMALL-CUP ACT PICK ==="
"$repo_root/scripts/jetson_robot_exec.sh" \
  --wrist-a --white --interactive -- \
  env FORESTBRIDGE_GEMINI_SHARED_DIR="$shared_dir" \
    python3 tools/run_with_shared_gemini.py \
      --script tools/act_white_short_rollout.py \
      --task "Pick up the red small measuring cup, retract slightly, and hold the grasp." \
      --checkpoint /data/models/act_small_cup_pick_006000 \
      --dataset-root /data/act/small_measuring_cup_pick_workspace10cm_v1 \
      --repo-id local/small_measuring_cup_pick_workspace10cm_v1 \
      --folded-pose-json /data/act/config/white_empty_folded_pose_v2.json \
      --endpoint-pose-json /workspace/configs/act/small_cup_pick_endpoint_v1.json \
      --device cuda \
      --steps "$steps" \
      --hold-at-end-s 10 \
      --max-arm-step-deg 1.5 \
      --max-gripper-step 3 \
      --max-total-arm-travel-deg 100 \
      --max-total-elbow-travel-deg 145 \
      --max-total-gripper-travel 60 \
      --grasp-supervisor \
      --execute
