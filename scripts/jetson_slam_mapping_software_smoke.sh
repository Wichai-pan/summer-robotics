#!/usr/bin/env bash
set -euo pipefail

# Container-only compatibility test for the exact RTAB-Map mapping graph.
# It maps no USB device and sends no motor command.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

exec docker run --rm \
  --mount "type=bind,src=$repo_root,dst=/workspace,readonly" \
  --workdir /workspace \
  "$image_name" \
  bash scripts/slam_static_odom_container.sh \
    --mode mapping \
    --transform-config configs/slam/base_to_gemini_candidate.yaml \
    --duration 10 \
    --dry-run
