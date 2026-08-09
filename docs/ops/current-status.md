# ForestBridge Robot Status

> Working memory only. Re-verify network, Git, devices, and permissions before acting.

## Stable Pointers

- Default server: `xlerobot-jetson`
- Personal SSH alias used on the current Mac: `jetsonl7`
- Git remote / branch: `origin/main`
- Local repo: `/Users/huataipan/Wichai/Hackathons/summer-robotics`
- Planned server repo: `/home/jetsonl7/summer-robotics-deploy`
- Server launch mode: direct SSH or `tmux`; no scheduler

## Current Focus

- Use the black arm as a torque-free leader and the white arm as a follower for ACT/VLA demonstration collection.
- Keep all robot USB ownership and execution on the onboard Jetson.
- Keep GitHub `main` as the code source of truth; treat `/robot-data/tmp` only as an experiment area.

## Latest Verified Server State

- Verified: 2026-08-09
- Host/user: `jetsonl7-desktop` / `jetsonl7`
- Network: Wi-Fi `192.168.0.48`; `.local` hostname is normally available on the same LAN.
- Platform: Jetson Orin Nano Super, Ubuntu 22.04.5, L4T 36.4.4, aarch64.
- Compute: CUDA 12.6 toolkit and TensorRT 10.3 installed; system Python 3.10 has no PyTorch.
- Storage: root filesystem has approximately 89 GB free.
- Deployment: `/home/jetsonl7/summer-robotics-deploy` tracks `origin/main`; private `.env`, YOLO weights, and three robot calibration files have been copied separately.
- Runtime: Docker and NVIDIA Container Toolkit are installed. `forestbridge-xlerobot:jp62` is built from NVIDIA 25.06 iGPU and passes Python 3.12 / Orin CUDA / LeRobot / NumPy-to-CUDA smoke tests.
- Perception runtime: `pyorbbecsdk2 2.1.1` ARM64 imports alongside NumPy 1.26.4 and OpenCV 4.11. Gemini produced valid RGB-D snapshots from the locked container (MJPEG, 3/3 and 5/5 trials).
- Gemini 335: online at USB 3 / 5 Gbps, serial `CP0F463000WA`, video nodes 0–7.
- Wrist cameras: both online and visually verified at 1280×720 MJPEG after removing their lens caps; they share a USB 2.0 480 Mbps upstream link and have duplicate USB serial strings.
- Control boards: online as `/dev/ttyACM0` serial `5B3D040988` and `/dev/ttyACM1` serial `5B3D043224`.
- Container port resolution: verified `white -> ttyACM0` and `black -> ttyACM1` using read-only device mappings; no motor bus was opened.
- Concurrency: `scripts/jetson_robot_exec.sh` minimally maps requested devices and the host lock was verified to reject a second container with exit code 3.
- SSH keyboard control: the previously verified `tools/arm_keyboard.py` now supports `--terminal`; the Jetson container help/import path and POSIX terminal backend were verified without opening a motor port.
- Robot calibration: `black_arm.json`, `white_arm.json`, and the XLeRobot calibration cache are mounted read-only into hardware containers.
- Remote access: Tailscale is installed; the Jetson node is shared separately from repository credentials. Physical motion still requires an on-site operator.
- Leader/follower: black-to-white relative following works for shoulder, elbow, wrist flex and gripper. The cyclic `wrist_roll` now uses a separately validated velocity loop rather than a wrap-crossing position target.
- Wrist validation: raw encoder wrap was crossed successfully without a long-path turn; a 45° trial reached leader `+42.4°` / follower `+37.0°` before the configured boundary and stopped with zero velocity and torque release.
- Safe combined controller: `tools/black_leads_white_wrap_safe.py` was physically tested; the operator confirmed the wrist can now reach most required positions.
- Closeout sync: local `main`, GitHub `origin/main`, and `/home/jetsonl7/summer-robotics-deploy` were aligned on 2026-08-09. The formal Jetson clone was clean and passed all 14 leader/follower unit tests in the production container.

## Open Issues

- Wrist cameras require stable names based on USB physical paths, not `/dev/videoN` or duplicate `by-id` names.
- Wrist path `2.4.1` (A) still shows the previously observed fixed edge blemish and is therefore probably the white-arm camera; path `2.4.3` (B) has no comparable mark. Confirm the arm labels physically before making them stable aliases.
- Camera GUI tools still need headless/web alternatives for remote use; the primary arm keyboard controller no longer depends on `pynput` when run with `--terminal`.
- The hardware lock only protects commands that use `scripts/jetson_robot_exec.sh`; direct `docker run` or host processes bypass it and are forbidden for team operation.
- LeRobot calibration cache, LLM `.env`, and YOLO weights remain machine state outside Git, although they are present on this Jetson.
- Cross-internet access exists through Tailscale, but remote physical control still lacks a disconnect watchdog and remains prohibited without an on-site operator.
- The two arms use different calibrated numerical zero references. Automatic absolute-angle alignment is not trusted; the current controller uses per-session relative zero points.
- The legacy `tools/black_leads_white_smoke.py` is motion-locked after a wrist overload caused by position control across the 0/4095 encoder wrap.

## Next Step

1. Re-run `tools/black_leads_white_wrap_safe.py` from the formal Jetson deployment clone after Git sync.
2. Connect the relative leader/follower stream to LeRobot dataset recording with synchronized observations, actions and cameras.
3. Record short, fixed-table successful demonstrations for the same face-cream pickup and train an ACT baseline.
4. Add per-person accounts plus a motor disconnect watchdog before any cross-internet physical operation.
