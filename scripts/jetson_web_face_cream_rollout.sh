#!/usr/bin/env bash
set -euo pipefail

# The web task reaches this wrapper only after the Jetson-local allow-list and
# one-shot onsite lease have been validated.  Keep recovery inside that same
# bounded task so an operator does not have to manually reset a slightly moved
# arm before every web run.

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

echo "=== 1/2 RETURN WHITE ARM TO FOLDED START POSE ==="
"$repo_root/scripts/jetson_robot_exec.sh" \
  --white --interactive -- \
  python3 tools/return_white_to_folded_pose.py \
    --timeout-s 60 \
    --execute

echo "=== 2/2 RUN FIXED-WORKSPACE SMOLVLA PICK/PLACE ==="
"$repo_root/scripts/jetson_smolvla_white_rollout.sh" \
  --execute \
  --steps "$steps"
