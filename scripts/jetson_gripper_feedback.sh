#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_gripper_feedback.sh {open|empty_close|grasp|slip} [NOTE]

Capture one supervised, labelled white-gripper feedback trial on Jetson.
The JSON result is written below:
  /home/jetsonl7/robot-data/act/gripper_feedback_v1/
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
[[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 2; }
label="$1"
case "$label" in
  open|empty_close|grasp|slip) ;;
  *) echo "Unknown label: $label" >&2; usage >&2; exit 2 ;;
esac
note="${2:-}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

exec "$repo_root/scripts/jetson_robot_exec.sh" \
  --white --interactive -- \
  python3 tools/capture_white_gripper_feedback.py \
  --label "$label" \
  --note "$note" \
  --execute
