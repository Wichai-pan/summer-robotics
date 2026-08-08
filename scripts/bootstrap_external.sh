#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
external_root="$repo_root/external"

clone_dependency() {
  local url="$1"
  local destination="$2"

  if [[ -d "$destination" ]]; then
    echo "keep existing: $destination"
    return
  fi

  git clone --depth 1 "$url" "$destination"
}

mkdir -p "$external_root"
clone_dependency "https://github.com/huggingface/lerobot.git" "$external_root/lerobot"
clone_dependency "https://github.com/Vector-Wangel/XLeRobot.git" "$external_root/XLeRobot"

echo "External source dependencies are ready under $external_root"
echo "Install or download the platform-specific Orbbec SDK separately when needed."
