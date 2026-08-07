#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jetson_robot_exec.sh [devices...] -- COMMAND [ARG...]

Device flags (only requested devices are exposed to the container):
  --gemini          Gemini 335 raw USB device and all of its V4L nodes
  --white           white-arm/base controller (USB serial 5B3D040988)
  --black           black-arm/head controller (USB serial 5B3D043224)
  --ports-readonly  both controller nodes with read-only device permission
  --wrist-a         wrist camera at physical USB path 2.4.1, index0
  --wrist-b         wrist camera at physical USB path 2.4.3, index0

Examples:
  ./scripts/jetson_robot_exec.sh --ports-readonly -- python3 tools/portutil.py
  ./scripts/jetson_robot_exec.sh --gemini -- python3 tools/orbbec_rgbd_snapshot.py --samples 5 --output /data/tmp/rgb.jpg

All invocations share one non-blocking host lock. No command starts if another
ForestBridge hardware container is still running.
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="${FORESTBRIDGE_IMAGE:-forestbridge-xlerobot:jp62}"
data_root="${FORESTBRIDGE_DATA_ROOT:-/home/jetsonl7/robot-data}"
calibration_root="${FORESTBRIDGE_CALIBRATION_ROOT:-/home/jetsonl7/.cache/huggingface/lerobot/calibration}"
lock_path="${FORESTBRIDGE_HARDWARE_LOCK:-/tmp/forestbridge-xlerobot.lock}"

device_args=()

resolve_board() {
  local serial="$1"
  local mode="${2:-rw}"
  local link="/dev/serial/by-id/usb-1a86_USB_Single_Serial_${serial}-if00"
  local target
  [[ -e "$link" ]] || { echo "Missing controller $serial ($link)" >&2; exit 2; }
  target="$(readlink -f "$link")"
  device_args+=(--device "$target:$target:$mode")
}

resolve_wrist() {
  local usb_port="$1"
  local link
  link="$(compgen -G "/dev/v4l/by-path/*usb-0:${usb_port}:1.0-video-index0" | head -n 1 || true)"
  [[ -n "$link" && -e "$link" ]] || { echo "Missing wrist camera at USB path $usb_port" >&2; exit 2; }
  local target
  target="$(readlink -f "$link")"
  device_args+=(--device "$target:/dev/wrist-${usb_port//./-}:rw")
}

resolve_gemini() {
  local row bus dev usb_node node vendor
  row="$(lsusb -d 2bc5:0800)"
  [[ "$(printf '%s\n' "$row" | sed '/^$/d' | wc -l)" -eq 1 ]] || {
    echo "Expected exactly one Gemini 335 (2bc5:0800), got: $row" >&2
    exit 2
  }
  bus="$(awk '{print $2}' <<<"$row")"
  dev="$(awk '{gsub(":", "", $4); print $4}' <<<"$row")"
  usb_node="/dev/bus/usb/$bus/$dev"
  [[ -e "$usb_node" ]] || { echo "Missing Gemini USB node $usb_node" >&2; exit 2; }
  device_args+=(--device "$usb_node:$usb_node:rw")

  for node in /dev/video*; do
    [[ -e "$node" ]] || continue
    vendor="$(udevadm info -q property -n "$node" 2>/dev/null | sed -n 's/^ID_VENDOR_ID=//p')"
    if [[ "$vendor" == "2bc5" ]]; then
      device_args+=(--device "$node:$node:rw")
    fi
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gemini) resolve_gemini; shift ;;
    --white) resolve_board 5B3D040988; shift ;;
    --black) resolve_board 5B3D043224; shift ;;
    --ports-readonly)
      resolve_board 5B3D040988 r
      resolve_board 5B3D043224 r
      shift
      ;;
    --wrist-a) resolve_wrist 2.4.1; shift ;;
    --wrist-b) resolve_wrist 2.4.3; shift ;;
    --) shift; break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ $# -gt 0 ]] || { echo "Missing command after --" >&2; usage >&2; exit 2; }
[[ -d "$data_root" ]] || { echo "Missing data root: $data_root" >&2; exit 2; }
[[ -d "$calibration_root" ]] || { echo "Missing calibration root: $calibration_root" >&2; exit 2; }

docker_cmd=(docker run --rm \
  --runtime nvidia \
  --ipc host \
  "${device_args[@]}" \
  --mount "type=bind,src=$repo_root,dst=/workspace" \
  --mount "type=bind,src=$data_root,dst=/data" \
  --mount "type=bind,src=$calibration_root,dst=/root/.cache/huggingface/lerobot/calibration,readonly" \
  --workdir /workspace \
  --env PYTHONPATH=/workspace/tools:/workspace/external/lerobot/src \
  "$image_name" \
  "$@")

# Use flock's parent-process mode. It holds the lock while the Docker child is
# running, independent of which file descriptors the Go Docker client closes.
set +e
flock --nonblock --conflict-exit-code 3 "$lock_path" "${docker_cmd[@]}"
status=$?
set -e
if [[ $status -eq 3 ]]; then
  echo "Robot hardware is already in use (lock: $lock_path). Stop the other session first." >&2
fi
exit "$status"
