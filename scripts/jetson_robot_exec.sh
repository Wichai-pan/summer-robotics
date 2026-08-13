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
  --interactive     attach the current SSH terminal to Docker (for keyboard/input tools)
  --x11             forward a container GUI to the SSH client's X11 display (no hardware implied)

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
interactive_args=()
x11_args=()

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
    --interactive) interactive_args=(-i -t); shift ;;
    --x11)
      [[ -n "${DISPLAY:-}" ]] || {
        echo "--x11 requires an SSH session with X11 forwarding (reconnect with: ssh -Y ...)." >&2
        exit 2
      }
      xauthority_path="${XAUTHORITY:-$HOME/.Xauthority}"
      [[ -r "$xauthority_path" ]] || {
        echo "--x11 cannot read Xauthority file: $xauthority_path" >&2
        exit 2
      }
      # SSH's X11 proxy listens on the Jetson loopback interface. Host networking
      # lets the container reach it, while Xauthority keeps the proxy protected.
      x11_args=(
        --network host
        --env "DISPLAY=$DISPLAY"
        --env XAUTHORITY=/root/.Xauthority
        --env QT_X11_NO_MITSHM=1
        --env LIBGL_ALWAYS_SOFTWARE=1
        --mount "type=bind,src=$xauthority_path,dst=/root/.Xauthority,readonly"
      )
      shift
      ;;
    --) shift; break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ $# -gt 0 ]] || { echo "Missing command after --" >&2; usage >&2; exit 2; }
[[ -d "$data_root" ]] || { echo "Missing data root: $data_root" >&2; exit 2; }
[[ -d "$calibration_root" ]] || { echo "Missing calibration root: $calibration_root" >&2; exit 2; }

container_cidfile="$(mktemp /tmp/forestbridge-container.XXXXXX.cid)"
rm -f "$container_cidfile"
container_token="${container_cidfile%.cid}"
container_token="${container_token##*.}"
container_name="forestbridge-session-$container_token"
session_pid="$$"
session_start="$(awk '{print $22}' "/proc/$session_pid/stat")"
watchdog_pid=""

# EXIT traps cannot run after SIGKILL. Keep a detached watchdog tied to this
# exact shell process so an abruptly lost SSH session cannot orphan Docker.
setsid bash -c '
  session_pid="$1"
  session_start="$2"
  cidfile="$3"
  container_name="$4"
  while [[ -r "/proc/$session_pid/stat" ]] &&
        [[ "$(awk '\''{print $22}'\'' "/proc/$session_pid/stat" 2>/dev/null)" == "$session_start" ]]; do
    sleep 1
  done
  # Docker may not have written the CID when the owner dies. The unique name
  # exists before launch, so wait briefly for an in-flight docker run.
  for attempt in {1..20}; do
    container_ref="$container_name"
    if ! docker inspect "$container_ref" >/dev/null 2>&1 && [[ -s "$cidfile" ]]; then
      container_ref="$(<"$cidfile")"
    fi
    if docker inspect "$container_ref" >/dev/null 2>&1; then
      docker stop --timeout 10 "$container_ref" >/dev/null 2>&1 ||
        docker kill "$container_ref" >/dev/null 2>&1 || true
      break
    fi
    sleep 1
  done
  rm -f "$cidfile"
' _ "$session_pid" "$session_start" "$container_cidfile" "$container_name" \
  </dev/null >/dev/null 2>&1 &
watchdog_pid=$!

docker_cmd=(docker run --rm \
  --name "$container_name" \
  --cidfile "$container_cidfile" \
  "${interactive_args[@]}" \
  "${x11_args[@]}" \
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

cleanup_container() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [[ -n "$watchdog_pid" ]]; then
    kill "$watchdog_pid" >/dev/null 2>&1 || true
  fi
  wait_attempts=1
  if [[ $status -ge 128 ]]; then
    wait_attempts=20
  fi
  for ((attempt = 1; attempt <= wait_attempts; attempt++)); do
    container_ref="$container_name"
    if ! docker inspect "$container_ref" >/dev/null 2>&1 && [[ -s "$container_cidfile" ]]; then
      container_ref="$(<"$container_cidfile")"
    fi
    if docker inspect "$container_ref" >/dev/null 2>&1; then
      echo "Stopping container $container_ref after host session exit." >&2
      docker stop --timeout 10 "$container_ref" >/dev/null 2>&1 || \
        docker kill "$container_ref" >/dev/null 2>&1 || true
      break
    fi
    if ((attempt < wait_attempts)); then
      sleep 1
    fi
  done
  rm -f "$container_cidfile"
  exit "$status"
}

trap cleanup_container EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

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
