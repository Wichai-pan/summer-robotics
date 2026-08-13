#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"
config_path="configs/slam/base_to_gemini_candidate.yaml"
dry_run=false

arguments=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_path="${2:?missing config}"; shift 2 ;;
    --dry-run) dry_run=true; arguments+=("--dry-run"); shift ;;
    --output-root|--output-root=*) echo "--output-root is managed by the Jetson wrapper" >&2; exit 2 ;;
    *) arguments+=("$1"); shift ;;
  esac
done

if [[ "$dry_run" == true ]]; then
  # Software-only validation: no /data mount, devices, or global hardware lock.
  exec docker run --rm \
    --env ROS_DOMAIN_ID="${FORESTBRIDGE_SLAM_DRY_RUN_DOMAIN_ID:-179}" \
    --mount "type=bind,src=$repo_root,dst=/workspace,readonly" \
    --workdir /workspace \
    "$image_name" \
    bash scripts/slam_static_odom_container.sh --mode motion \
      --transform-config "$config_path" "${arguments[@]}"
fi

echo "Motion VO live mode is blocked: it needs one future supervisor session to own the"
echo "shared hardware lock while coordinating Gemini recording and manual base control."
echo "No controller serial port is mapped by this entry. Use --dry-run until that session is reviewed."
exit 2
