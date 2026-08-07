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
- Deployment: `/home/jetsonl7/summer-robotics-deploy` tracks `origin/main`; private `.env`, YOLO weights, and three robot calibration files have been copied separately.
- Runtime: Docker and NVIDIA Container Toolkit are installed. The versioned `forestbridge-xlerobot:jp62` image has not been built yet.
- Gemini 335: online at USB 3 / 5 Gbps, serial `CP0F463000WA`, video nodes 0–7.
- Wrist cameras: both online, but share a USB 2.0 480 Mbps upstream link and have duplicate USB serial strings.
- Control boards: online as `/dev/ttyACM0` serial `5B3D040988` and `/dev/ttyACM1` serial `5B3D043224`.

## Open Issues

- `jetsonl7` belongs to `video` but not `dialout`; ordinary-user serial access is currently blocked.
- Wrist cameras require stable names based on USB physical paths, not `/dev/videoN` or duplicate `by-id` names.
- The Jetson iGPU Python image and Linux aarch64 Orbbec SDK are not installed yet.
- Existing GUI (`cv2.imshow`) and `pynput` scripts need headless/terminal-native alternatives for SSH use.
- There is no cross-process hardware lock; multiple SSH users must not open motor controllers concurrently.
- LeRobot calibration cache, LLM `.env`, and YOLO weights are machine state and do not come from Git.

## Next Step

1. Add `jetsonl7` to `dialout` and `docker`, then completely log out and reconnect.
2. Pull/build the NVIDIA 25.06 iGPU-derived image and run the no-USB GPU/LeRobot smoke test.
3. Install the Linux aarch64 Orbbec SDK inside the derived image.
4. Perform read-only board identification and validate cameras one at a time before any motion.
