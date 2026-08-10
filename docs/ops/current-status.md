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

- Verified: 2026-08-10
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
- ACT recorder candidate: a temporary Jetson image built from pinned LeRobot
  `22bd7a2f489b367d8df42de803b1e8c4ca63a3f9` (0.6.2) passed synthetic
  create -> save -> finalize -> reopen with 10 frames and two encoded videos.
- ACT camera preflight: Gemini plus each wrist path independently delivered
  60/60 unique 640x480 RGB samples with no duplicate control samples and
  maximum observed frame age below 30 ms. No motor devices were mapped.
- ACT formal deployment: local `main`, GitHub `origin/main`, and the clean
  Jetson deployment clone were fast-forwarded to `3e74d4e`. The formal
  `forestbridge-xlerobot:jp62` image was rebuilt with LeRobot 0.6.2,
  `datasets 4.8.5`, and PyAV 15.1.0. GPU/import smoke passed.
- ACT formal dataset smoke: create -> save -> finalize -> reopen passed with
  one 10-frame/two-video synthetic episode at
  `/home/jetsonl7/robot-data/act-smoke/20260810-formal-recorder-v1/dataset`.
- ACT formal camera smoke: Gemini and white wrist (`2.4.1`) each produced
  60/60 unique RGB samples with no duplicates; maximum ages were 25 ms and
  35 ms. No motor device was mapped.
- ACT pilot corpus: 11 successful episodes / 9,563 frames at 20 FPS are stored
  on Jetson under `/home/jetsonl7/robot-data/act/fixed_pick_place_v1`.
- ACT training: Roihu job `572912` produced checkpoint step 6,000. The durable
  `/projappl` copy is backup only; Jetson inference reads
  `/home/jetsonl7/robot-data/models/act_fixed_pick_place_572912_006000`.
- ACT Jetson deployment gate: checkpoint loading, dataset/video decoding and
  CUDA inference passed on 11 recorded frames without mapping any USB device.
  Mean absolute errors were 1.91° shoulder pan, 0.84° shoulder lift, 4.26°
  elbow, 1.76° wrist flex, 0.004°/s wrist roll and 1.77 gripper units.
- ACT live-camera gate: one Gemini + white-wrist RGB pair entered ACT on the
  Jetson and produced a finite six-dimensional action. No serial/motor device
  was mapped. This test deliberately reused a recorded state vector and was
  not a physical rollout.

## Open Issues

- Wrist camera identity was confirmed on 2026-08-10 using the previously
  observed fixed edge blemish on the white-arm camera: physical path `2.4.1`
  (`--wrist-a`, container `/dev/wrist-2-4-1`) is white; `2.4.3`
  (`--wrist-b`, `/dev/wrist-2-4-3`) is black. Continue using physical paths,
  never `/dev/videoN` or duplicate `by-id` names.
- Camera GUI tools still need headless/web alternatives for remote use; the primary arm keyboard controller no longer depends on `pynput` when run with `--terminal`.
- The hardware lock only protects commands that use `scripts/jetson_robot_exec.sh`; direct `docker run` or host processes bypass it and are forbidden for team operation.
- LeRobot calibration cache, LLM `.env`, and YOLO weights remain machine state outside Git, although they are present on this Jetson.
- Cross-internet access exists through Tailscale, but remote physical control still lacks a disconnect watchdog and remains prohibited without an on-site operator.
- The two arms use different calibrated numerical zero references. Automatic absolute-angle alignment is not trusted; the current controller uses per-session relative zero points.
- The legacy `tools/black_leads_white_smoke.py` is motion-locked after a wrist overload caused by position control across the 0/4095 encoder wrap.
- ACT predictions sometimes slightly exceed the pilot corpus min/max (in the
  11-frame check: shoulder lift 1, elbow 3, wrist flex 4, gripper 2). A live
  executor must clamp to trusted bounds and enforce rate/step limits.
- The fixed-pose JSON wrist angle and the recorder's velocity-mode wrist state
  can use different numeric branches around the 0/4095 wrap. Do not feed the
  JSON wrist value directly into ACT; reconstruct state using the same mode and
  branch semantics as the recorder.

## Next Step

1. Add a torque-free white-arm state reader that reproduces the recorder's
   wrist branch semantics; combine it with live cameras for a no-motion test.
2. Add per-joint training-range clamps, rate/step limits, stale-frame stops,
   hardware locking and an on-site dead-man confirmation to the ACT executor.
3. Run a torque-enabled hold-only test, then a bounded one-step test from the
   fixed folded pose; do not start a continuous rollout first.
4. Expand the dataset after reviewing the first bounded physical behavior;
   11 highly similar episodes are enough for a pipeline smoke test, not robust
   generalization.
