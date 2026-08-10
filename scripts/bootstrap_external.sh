#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
external_root="$repo_root/external"
lerobot_ref="${LEROBOT_REF:-22bd7a2f489b367d8df42de803b1e8c4ca63a3f9}"
xlerobot_ref="${XLEROBOT_REF:-3d14695e40c9c68229c0aacffca6053c75cd3eb6}"

clone_dependency() {
  local url="$1"
  local destination="$2"
  local ref="$3"

  if [[ -d "$destination" ]]; then
    if [[ ! -d "$destination/.git" ]]; then
      echo "Existing dependency is not an independent Git checkout: $destination" >&2
      echo "Move it aside, then rerun this script; it will not overwrite local files." >&2
      return 2
    fi
    local current
    current="$(git -C "$destination" rev-parse HEAD)"
    if [[ "$current" != "$ref" ]]; then
      echo "Dependency version mismatch: $destination" >&2
      echo "  expected: $ref" >&2
      echo "  current:  $current" >&2
      echo "Use a clean checkout at the pinned commit; this script will not reset local work." >&2
      return 2
    fi
    echo "verified pinned dependency: $destination @ $ref"
    return
  fi

  mkdir -p "$destination"
  git -C "$destination" init
  git -C "$destination" remote add origin "$url"
  git -C "$destination" fetch --depth 1 origin "$ref"
  git -C "$destination" checkout --detach FETCH_HEAD
  echo "installed pinned dependency: $destination @ $ref"
}

mkdir -p "$external_root"
clone_dependency "https://github.com/huggingface/lerobot.git" "$external_root/lerobot" "$lerobot_ref"
clone_dependency "https://github.com/Vector-Wangel/XLeRobot.git" "$external_root/XLeRobot" "$xlerobot_ref"

echo "External source dependencies are ready under $external_root"
echo "LeRobot commit: $lerobot_ref"
echo "XLeRobot commit: $xlerobot_ref"
echo "Install or download the platform-specific Orbbec SDK separately when needed."
