# ForestBridge Robot Operations Decision Log

## 2026-08-07 — Jetson is the robot hardware host

- All robot USB devices connect to the onboard Jetson; laptops connect over SSH/Wi-Fi.
- GitHub remains the code source of truth. The Jetson uses a deployment clone rather than ad-hoc copied source trees.
- Each developer may use a separate clone/worktree, but only one controlled deployment process may own motor hardware.
- Real movement requires a person physically present with immediate power-cut access.
- Revisit if network reliability cannot support supervision or if a dedicated onboard control service replaces direct SSH runs.

## 2026-08-07 — Separate perception and robot environments

- Maintain persistent `lerobot` and `orbbec-depth` environments on the Jetson.
- Preserve JetPack CUDA/TensorRT packages and verify an NVIDIA-compatible PyTorch build before installation.
- Install the Linux aarch64 Orbbec SDK; the macOS SDK is never copied to the Jetson.

## 2026-08-07 — Stable device identity and permissions

- Control boards are identified by their USB serial numbers, not `/dev/ttyACM` enumeration order.
- Duplicate wrist-camera serials require physical USB-path aliases.
- Use `dialout`/`video` groups and scoped udev rules; do not normalize recurring `chmod 666` or sudo camera execution.

## 2026-08-07 — Server command and Git safety

- Use the configured SSH alias and simple argv-style remote commands; promote complex remote logic to versioned scripts.
- Require clean Git state and fast-forward-only deployment updates.
- Never reset, clean, or overwrite a dirty deployment clone without explicit approval.
