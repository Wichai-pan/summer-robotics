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
- Runtime: Docker and NVIDIA Container Toolkit are installed. `forestbridge-xlerobot:jp62` is built from NVIDIA 25.06 iGPU and passes Python 3.12 / Orin CUDA / LeRobot / NumPy-to-CUDA smoke tests.
- Perception runtime: `pyorbbecsdk2 2.1.1` ARM64 imports alongside NumPy 1.26.4 and OpenCV 4.11. Gemini produced valid RGB-D snapshots from the locked container (MJPEG, 3/3 and 5/5 trials).
- Gemini 335: online at USB 3 / 5 Gbps, serial `CP0F463000WA`, video nodes 0–7.
- Wrist cameras: both online, but share a USB 2.0 480 Mbps upstream link and have duplicate USB serial strings.
- Control boards: online as `/dev/ttyACM0` serial `5B3D040988` and `/dev/ttyACM1` serial `5B3D043224`.
- Container port resolution: verified `white -> ttyACM0` and `black -> ttyACM1` using read-only device mappings; no motor bus was opened.
- Concurrency: `scripts/jetson_robot_exec.sh` minimally maps requested devices and the host lock was verified to reject a second container with exit code 3.

## Open Issues

- Wrist cameras require stable names based on USB physical paths, not `/dev/videoN` or duplicate `by-id` names.
- Both wrist cameras return valid 1280×720 MJPEG frames, but the captured content is nearly black (mean 1.5/255 after 60 warm-up frames); physical occlusion/orientation must be checked before visual acceptance.
- Existing GUI (`cv2.imshow`) and `pynput` scripts need headless/terminal-native alternatives for SSH use.
- The hardware lock only protects commands that use `scripts/jetson_robot_exec.sh`; direct `docker run` or host processes bypass it and are forbidden for team operation.
- LeRobot calibration cache, LLM `.env`, and YOLO weights remain machine state outside Git, although they are present on this Jetson.

## Next Step

1. Physically uncover/reorient both wrist cameras, then repeat per-camera frame validation and label path `2.4.1` / `2.4.3` as white or black arm.
2. Add a terminal-native, headless wrist-camera snapshot/stream command for SSH use.
3. Inspect the existing bus monitor and perform position-only motor reads through the locked wrapper; do not enable torque.
4. Only after those checks, perform a supervised single-joint or fixed base motion on Jetson.
