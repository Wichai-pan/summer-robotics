#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_smolvla_white_rollout.sh [--execute] [--steps N]

Without --execute, loads one live shared Gemini frame and one wrist frame,
runs the guarded SmolVLA policy, and never enables torque or sends an action.
Physical execution requires --execute, an interactive TTY, an on-site operator,
and an available emergency cutoff.

The Hugging Face base model is loaded from the persistent offline cache prepared
by scripts/jetson_prepare_smolvla_cache.sh. The rollout never downloads models.
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/forestbridge_task_preview_env.sh"
source "$repo_root/scripts/forestbridge_broker_task_guard.sh"
execute_args=()
interactive_args=()
steps=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) execute_args=(--execute); interactive_args=(--interactive); shift ;;
    --steps)
      [[ $# -ge 2 ]] || { echo "--steps requires a value" >&2; exit 2; }
      steps="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$steps" =~ ^[0-9]+$ ]] && ((steps >= 1 && steps <= 600)) || {
  echo "--steps must be an integer in [1, 600]" >&2
  exit 2
}

shared_dir="${FORESTBRIDGE_GEMINI_SHARED_DIR:-/dev/shm/forestbridge-gemini}"
[[ -s "$shared_dir/latest.jpg" && -s "$shared_dir/latest.json" ]] || {
  echo "Gemini broker frame is unavailable: $shared_dir" >&2
  echo "Start scripts/jetson_gemini_rgbd_broker.sh first." >&2
  exit 3
}

trap forestbridge_broker_task_guard_end EXIT
forestbridge_broker_task_guard_begin

hf_hub_cache="${FORESTBRIDGE_SMOLVLA_HF_HUB_CACHE:-/data/cache/huggingface/hub}"
host_data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
host_hf_snapshot_root="$host_data_root/cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots"
if ! compgen -G "$host_hf_snapshot_root/*" >/dev/null; then
  echo "Persistent SmolVLA base-model cache is missing." >&2
  echo "Run once: bash scripts/jetson_prepare_smolvla_cache.sh" >&2
  exit 3
fi

"$repo_root/scripts/jetson_robot_exec.sh" \
  --wrist-a --white "${interactive_args[@]}" -- \
  env \
    FORESTBRIDGE_GEMINI_SHARED_DIR="$shared_dir" \
    HF_HUB_CACHE="$hf_hub_cache" \
    HUGGINGFACE_HUB_CACHE="$hf_hub_cache" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONPATH=/data/tmp/smolvla-latency-20260907/pydeps:/workspace/tools:/workspace/external/lerobot/src \
  python3 /workspace/tools/run_with_shared_gemini.py \
    --script /workspace/tools/smolvla_white_rollout.py \
    --task "Pick up the blue face-cream jar from the fixed point, place it at the fixed target, and return the white arm to its folded rest pose." \
    --checkpoint /data/models/smolvla_fixed_pick_place_1097975_020000 \
    --dataset-root /data/act/fixed_pick_place_v1 \
    --rename-map observation.images.gemini_rgb=observation.images.camera1,observation.images.white_wrist_rgb=observation.images.camera2 \
    --steps "$steps" \
    --max-arm-step-deg 1.5 \
    --max-gripper-step 3 \
    --max-total-arm-travel-deg 100 \
    --max-total-elbow-travel-deg 130 \
    --max-total-gripper-travel 60 \
    --grasp-supervisor \
    "${execute_args[@]}"
