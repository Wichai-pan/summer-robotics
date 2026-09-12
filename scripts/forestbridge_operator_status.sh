#!/usr/bin/env bash
# Shared, non-control status reporter for operator-started Jetson workflows.
# Source this file from a wrapper and call forestbridge_operator_status_set.

forestbridge_operator_status_set() {
  local phase="$1"
  local detail="${2:-}"
  local source_name="${3:-$(basename "${BASH_SOURCE[1]:-${0}}")}" 
  local data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
  local status_path="${FORESTBRIDGE_OPERATOR_STATUS_PATH:-$data_root/runtime/forestbridge-operator-status.json}"

  case "$phase" in
    idle|preparing|set_mapping_camera|set_grasp_camera|localizing|planning|navigating|grasping|holding|placing|verifying_result|needs_assistance) ;;
    *)
      echo "Unsupported ForestBridge operator phase: $phase" >&2
      return 2
      ;;
  esac

  mkdir -p "$(dirname "$status_path")"
  python3 - "$status_path" "$phase" "$detail" "$source_name" "$$" <<'PY'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

path, phase, detail, source, pid = sys.argv[1:]
payload = {
    "schema": "forestbridge/operator-status/v1",
    "phase": phase,
    "detail": detail[:240],
    "source": source[:160],
    "pid": int(pid),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
fd, temporary = tempfile.mkstemp(prefix=".forestbridge-operator-status-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.write("\n")
    os.replace(temporary, path)
    os.chmod(path, 0o600)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
  printf 'FORESTBRIDGE_OPERATOR_STATE phase=%s source=%s\n' "$phase" "$source_name"
}
