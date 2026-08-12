#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"
data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"

dry_run=false
for argument in "$@"; do
  case "$argument" in
    --dry-run)
      dry_run=true
      ;;
    --output-root|--output-root=*)
      echo "--output-root is managed by the Jetson wrapper" >&2
      exit 2
      ;;
  esac
done

if [[ "$dry_run" == true ]]; then
  # Software-only validation: no /data mount, device mapping, or hardware lock.
  exec docker run --rm \
    --mount "type=bind,src=$repo_root,dst=/workspace,readonly" \
    --workdir /workspace \
    "$image_name" \
    bash scripts/slam_static_odom_container.sh "$@"
fi

mkdir -p "$data_root/slam/static-odom"

# Gemini is the only exposed device. No controller serial port is mapped.
exec "$repo_root/scripts/jetson_slam_exec.sh" --gemini -- \
  bash scripts/slam_static_odom_container.sh \
    --output-root /data/slam/static-odom "$@"
