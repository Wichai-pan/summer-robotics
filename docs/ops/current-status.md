# ForestBridge Jetson Migration Status

> Working memory only. Re-verify network, Git, devices, and permissions before acting.

## Stable Pointers

- Default server: `xlerobot-jetson`
- Personal SSH alias used on the current Mac: `jetsonl7`
- Git remote / branch: `origin/main`
- Local repo: `/Users/huataipan/Wichai/Hackathons/summer-robotics`
- Planned server repo: `/home/jetsonl7/summer-robotics-deploy`
- Server launch mode: direct SSH or `tmux`; no scheduler

## Current Focus

- Move all robot USB ownership and execution from the developer Mac to the onboard Jetson.
- Keep GitHub as the code source of truth and make the Jetson deployment clone reproducible.
- Perform read-only enumeration before installing dependencies or commanding hardware.

## Latest Verified Server State

- Verified: 2026-08-07
- Host/user: `jetsonl7-desktop` / `jetsonl7`
- Network: Wi-Fi `192.168.0.48`; `.local` hostname is normally available on the same LAN.
- Platform: Jetson Orin Nano Super, Ubuntu 22.04.5, L4T 36.4.4, aarch64.
- Compute: CUDA 12.6 toolkit and TensorRT 10.3 installed; system Python 3.10 has no PyTorch.
- Storage: root filesystem has approximately 89 GB free.
- Project/Conda: no deployment clone or Conda/Miniforge environment existed at audit time.
- Gemini 335: online at USB 3 / 5 Gbps, serial `CP0F463000WA`, video nodes 0–7.
- Wrist cameras: both online, but share a USB 2.0 480 Mbps upstream link and have duplicate USB serial strings.
- Control boards: online as `/dev/ttyACM0` serial `5B3D040988` and `/dev/ttyACM1` serial `5B3D043224`.

## Open Issues

- `jetsonl7` belongs to `video` but not `dialout`; ordinary-user serial access is currently blocked.
- Wrist cameras require stable names based on USB physical paths, not `/dev/videoN` or duplicate `by-id` names.
- The main Python environments and Linux aarch64 Orbbec SDK are not installed.
- Existing GUI (`cv2.imshow`) and `pynput` scripts need headless/terminal-native alternatives for SSH use.
- There is no cross-process hardware lock; multiple SSH users must not open motor controllers concurrently.
- LeRobot calibration cache, LLM `.env`, and YOLO weights are machine state and do not come from Git.

## Next Step

1. Commit and push the reviewed local migration files without logs, secrets, or failed IK prototypes.
2. Clone `origin/main` into `/home/jetsonl7/summer-robotics-deploy`.
3. Resolve `dialout` membership, then log out/in and perform read-only board identification.
4. Install architecture-compatible Python environments and validate cameras one at a time.
