#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Preparing the persistent SmolVLA Hugging Face cache."
echo "This is a one-time network operation and opens no camera or motor device."

"$repo_root/scripts/jetson_robot_exec.sh" -- \
  env \
    HF_HUB_CACHE=/data/cache/huggingface/hub \
    HUGGINGFACE_HUB_CACHE=/data/cache/huggingface/hub \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONPATH=/data/tmp/smolvla-latency-20260907/pydeps:/workspace/external/lerobot/src \
  python3 /workspace/tools/prepare_smolvla_hf_cache.py \
    --cache-dir /data/cache/huggingface/hub

echo "Persistent cache is ready; rollout scripts now run with network access disabled."
