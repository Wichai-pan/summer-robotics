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
