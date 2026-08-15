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

- The 2026-08-14 fixed downward-Gemini supervised RGB-D mapping candidate
  `20260814T140025Z` passed at 7.143 Hz with zero tracking loss, a 0.467221 s
  maximum gap, 5.4 cm position closure and 0.71° orientation closure over a
  9.10 m manual route. It is the current RTAB-Map candidate for supervised
  localization/planning experiments, not yet a navigation-grade localization
  source. The fixed reference is raw gimbal ID7=4066/ID8=1924 and the candidate
  config is `configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml`.
  Next: localization-only restart at two known poses, then Nav2 planning
  dry-run; wheel/IMU fusion and `/cmd_vel` base control remain separate gates.
- Improve the fixed-scene ACT grasp by adding deterministic grasp-success feedback around the current policy.
- Use gripper position/current/load plus the white-wrist RGB stream to distinguish grasp, empty close, slip and jam before allowing transport.
- Keep all robot USB ownership and execution on the onboard Jetson.
- Keep GitHub `main` as the code source of truth; treat `/robot-data/tmp` only as an experiment area.
- Train a separate 28-episode ACT comparison checkpoint while retaining the original 11-episode corpus and step-6,000 checkpoint unchanged.

## Latest ACT v2 Result

- Completed 2026-08-13: Slurm job `616995` (`xlerobot-act-v2-28ep`) used one GH200 GPU in `gpularge` and completed 6,000 training steps in 00:06:18.
- Dataset copy: `/scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep`.
  It was copied from Jetson's `/home/jetsonl7/robot-data/act/fixed_pick_place_v1`
  after confirming 28 finalized episodes / 19,309 frames / 20 FPS and 28 videos for each RGB stream.
- Training source episodes are `0–23` (24 episodes / 17,222 frames); holdout episodes `24–27` were not used for training.
- The final checkpoint exists on Roihu and was copied without overwriting the old model to Jetson:
  `/home/jetsonl7/robot-data/models/act_fixed_pick_place_v2_28ep_616995_006000`.
- Read-only holdout inference job `617117` completed. On 12 sampled frames from episodes `24–27`, action MAE was 1.39° pan, 1.87° lift, 3.73° elbow, 1.06° wrist flex and 4.59 gripper units. This is a small temporal holdout check, not a physical success-rate claim.
- The v2 live-camera/state preflight passed with torque disabled and zero motion commands. Operator-supervised 200/400/600-step physical trials subsequently observed jar grasping; the 600-step run completed grasp, short left transfer and release, but did not finish a deterministic folded return.

## Latest Verified Server State

- Verified: 2026-08-11
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
- ACT physical rollout: matching the recorded 30°/s arm and 60 units/s gripper
  rates produced the first real face-cream pick, short transport and place.
- ACT repeatability: four controlled 30-second trials produced 0/4 strict
  successes, 1/4 partial success and 3/4 failures. All four executors completed
  600/600 steps without a hardware or inference abort.
- ACT long diagnostic: one 45-second run completed 900/900 steps but repeated
  approach/close/retract cycles and ended in another grasp pose. More rollout
  time does not supply the missing grasp-success signal.
- ACT trial logs: timestamped raw logs are under
  `/home/jetsonl7/robot-data/logs`; code, data and model remain separated.

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
- The current ACT observation does not include `Present_Load` or
  `Present_Current`. Wrist RGB can suggest whether the jar is present, but the
  checkpoint has no explicit contact or success signal and may restart the
  grasp after an unsuccessful partial return.

## Next Step

1. Measure white-gripper position, velocity, load and current for open, empty
   close, correct jar grasp and slip/jam cases without changing torque limits.
2. Define and validate a deterministic contact threshold on repeated samples.
3. Add a grasp supervisor around ACT: verify contact, lift 3–5 cm, confirm with
   white-wrist RGB, hold on success and permit at most 1–2 retries on failure.
4. Stop one trial after one completed attempt/return transition instead of
   extending rollout time into repeated grasp cycles.
5. After the supervisor is stable, collect additional clean demonstrations and
   decide whether load/current should become learned observation features.
