# ForestBridge Robot Operations Decision Log

## 2026-08-07 — Jetson is the robot hardware host

- All robot USB devices connect to the onboard Jetson; laptops connect over SSH/Wi-Fi.
- GitHub remains the code source of truth. The Jetson uses a deployment clone rather than ad-hoc copied source trees.
- Each developer may use a separate clone/worktree, but only one controlled deployment process may own motor hardware.
- Real movement requires a person physically present with immediate power-cut access.
- Revisit if network reliability cannot support supervision or if a dedicated onboard control service replaces direct SSH runs.

## 2026-08-07 — Versioned Jetson iGPU container

- Use NVIDIA's `nvcr.io/nvidia/pytorch:25.06-py3-igpu` as the Python 3.12 / GPU baseline on JetPack 6.2.
- Keep LeRobot, Feetech, and eventually Orbbec Python dependencies in one derived image; keep the host responsible only for Docker, udev, permissions, and locks.
- Install vendored LeRobot with `--no-deps` after explicit non-Torch dependencies. Never let generic pip resolution replace NVIDIA's Torch/Torchvision builds.
- Pin NumPy 1.26.4 and OpenCV 4.11 in the Jetson image: NVIDIA 25.06 iGPU Torch cannot use NumPy 2.x through `torch.from_numpy`, despite LeRobot's newer generic NumPy declaration.
- Install the official `pyorbbecsdk2==2.1.1` ARM64 wheel with `--no-deps`; its generic dependency set would otherwise replace the validated Jetson NumPy/OpenCV ABI stack.
- Install the Linux aarch64 Orbbec SDK in the derived image; the macOS SDK is never copied to the Jetson.
- Revisit a split host/container architecture only if Orbbec UVC/USB access proves unstable in the container.

## 2026-08-07 — Stable device identity and permissions

- Control boards are identified by their USB serial numbers, not `/dev/ttyACM` enumeration order.
- Duplicate wrist-camera serials require physical USB-path aliases.
- Use `dialout`/`video` groups and scoped udev rules; do not normalize recurring `chmod 666` or sudo camera execution.

## 2026-08-07 — Server command and Git safety

- Use the configured SSH alias and simple argv-style remote commands; promote complex remote logic to versioned scripts.
- Require clean Git state and fast-forward-only deployment updates.
- Never reset, clean, or overwrite a dirty deployment clone without explicit approval.

## 2026-08-07 — One locked, minimally mapped hardware container

- Run USB hardware commands through `scripts/jetson_robot_exec.sh`.
- Expose only explicitly requested camera/controller device nodes; never default to `--privileged`.
- Hold one host `flock` for the full container lifetime so separate SSH users cannot concurrently own robot hardware.
- Keep persistent outputs under `/home/jetsonl7/robot-data`; mount calibration read-only.

## 2026-08-07 — Preserve the verified arm controller across SSH

- `tools/arm_keyboard.py` remains the primary manual arm controller because it is the controller used to record and replay the successful physical grasp.
- Add a POSIX terminal input backend with `--terminal`; do not replace its joint mapping, calibration, P control, pose logging, or full working range with a new limited controller.
- Keep `tools/arm_terminal.py` only as a conservative connectivity diagnostic. Its startup-relative limits are intentional and it is not a substitute for full teleoperation.
- All SSH keyboard control still runs through `scripts/jetson_robot_exec.sh --interactive` and the shared hardware lock.

## 2026-08-09 — Relative leader/follower with a velocity-controlled cyclic wrist

- Do not align the white arm to the black arm by copying absolute calibrated angles: the two calibration files use different numerical zero references even when physical poses are similar.
- Define each arm's current pose as its own zero when the operator enters `FOLLOW`, then copy relative leader motion.
- Keep shoulder, elbow, wrist-flex and gripper in bounded/slewed position control.
- Never send a `wrist_roll` position target across encoder `4095/0`. Track its unwrapped relative displacement and command a bounded signed velocity instead.
- Keep a cable-safe accumulated wrist limit. At the limit, clamp the white-wrist target while keeping the session alive so returning the leader allows the follower to return.
- Keep the legacy mixed position-mode script motion-locked; use `tools/black_leads_white_wrap_safe.py` for subsequent demonstrations.

## 2026-08-10 — First ACT dataset is a fixed-scene white-arm task

- Each episode starts and ends in the same folded pose and performs one fixed
  face-cream pick and one fixed placement; scene variation is deferred until a
  reliable baseline exists.
- The black arm is a torque-free leader and diagnostic source. The future ACT
  policy observes white-arm state, Gemini RGB, and white-wrist RGB, and predicts
  commands for the white follower.
- Record the exact command actually sent: five slewed position goals plus the
  wrap-safe wrist-roll velocity. Do not mislabel wrist velocity as position.
- Only operator-approved complete episodes enter LeRobotDataset. Failed or
  interrupted trials go to a separate ledger, and every accepted episode must
  finalize and reopen successfully.
