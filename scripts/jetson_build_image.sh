#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="${FORESTBRIDGE_IMAGE:-forestbridge-xlerobot:jp62}"

cd "$repo_root"
docker build \
  --file deploy/jetson/Dockerfile \
  --tag "$image_name" \
  .

echo "Built $image_name"
