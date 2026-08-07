#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec "$repo_root/scripts/jetson_robot_exec.sh" --ports-readonly -- \
  python3 tools/portutil.py
