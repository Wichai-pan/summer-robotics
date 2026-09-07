#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
map_timestamp="${JETSON_HOME_MAP_TIMESTAMP:-20260902T194820Z}"
candidate="$repo_root/artifacts/slam/${map_timestamp}/navigation-work/rtabmap-candidate-working.db"
original="/home/jetsonl7/robot-data/slam/mapping/${map_timestamp}/rtabmap.db"
work="$repo_root/artifacts/slam/${map_timestamp}/navigation-work"
run_dir="${1:-}"
if [[ -z "$run_dir" ]]; then
  run_dir="$(find /home/jetsonl7/robot-data/slam/localization -mindepth 1 -maxdepth 1 \
    -type d -exec test -s '{}/localization-result.json' ';' -print | sort | tail -n 1)"
fi
[[ -n "$run_dir" ]] || { echo "No completed localization run found." >&2; exit 2; }

python3 "$repo_root/tools/audit_rtabmap_candidate.py" "$candidate" \
  --original "$original" --output "$work/database-audit.json"
python3 "$repo_root/tools/validate_localization_gate.py" "$run_dir" \
  --output "$work/localization-gate.json"

pose_args=($(python3 - "$run_dir/localization-result.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))["map_to_base_link"]["translation"]
print(p[0], p[1])
PY
))
python3 "$repo_root/tools/audit_occupancy_map.py" \
  --map-pgm "$run_dir/occupancy-map/map.pgm" \
  --map-yaml "$run_dir/occupancy-map/map.yaml" \
  --start-x "${pose_args[0]}" --start-y "${pose_args[1]}" \
  --robot-radius-m "${FORESTBRIDGE_ROBOT_RADIUS_M:-0.30}" \
  --safety-margin-m "${FORESTBRIDGE_SAFETY_MARGIN_M:-0.00}" \
  --output "$work/occupancy-audit.json" \
  --preview "$work/occupancy-clearance-preview.ppm"

echo "PASS: database, stationary localization, TF, and current footprint clearance gates."
