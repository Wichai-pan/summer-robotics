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

- September 11 web full-cycle integration (pending deployment): branch
  `codex/web-task-framework` adds two fixed web presets:
  `small_cup_system_prepare_01` starts/reuses the white-board and Gemini
  brokers without motion; `small_cup_full_cycle_01` delegates exclusively to
  the teammate's deployed Pick → table-to-sofa → sofa-to-table → Place script.
  The worker has a second Jetson-local allowlist, fixed argv, a 900-second
  local timeout and Relay Stop support. The final script exit means program
  completion only, not independently verified holding/delivery. See
  `docs/ops/web-small-cup-full-cycle-20260911.md`. Deploy only to the separate
  worker clone; do not disturb the teammates' dirty deployment worktree.

- September 11 small-cup segment training: the Jetson's finalized paired
  datasets were copied to the isolated Roihu SmolVLA root after matching their
  `meta/info.json` SHA256 values. `small_measuring_cup_pick_workspace10cm_v1`
  contains 60 episodes / 19,710 frames; episodes 0–53 (17,916 frames) train
  job `1270255` and 54–59 are held out. The initial log reached step 100 with
  stable ~7.9 GiB GPU memory and no dataset/model error. The independent
  `small_measuring_cup_place_workspace10cm_v1` contains 53 episodes / 20,383
  frames; episodes 0–47 train job `1270256` after job 1270255 ends, while
  48–52 are held out. Both use pretrained SmolVLA, 20,000 steps, batch 32,
  seed 42 and 4,000-step checkpoint saves. These are separate fixed-workspace
  policies, not an end-to-end holding/navigation model; quarantined Jetson
  data was excluded. Monitor `/scratch/project_2016517/panh/summer-robotics-smolvla/logs/fb-smolvla-cup-{pick,place}_<jobid>.out`.

- September 10 Git closeout: the web-to-Jetson task adapter, persistent Gemini
  broker, guarded/offline SmolVLA Jetson rollout and their handoff documents are
  now separated into reviewable commits on `origin/smolvla-longrun`. The local
  branch is the source of truth for this work; it has not been pulled into the
  teammate's dirty Jetson deployment clone. The old web task pose remains
  motion-locked because it does not match the team's September home map. Start
  teammate handoff at `docs/ops/team-handoff-20260910.md`.

- September 8 onsite handoff: the guarded SmolVLA executor completed a 20-step
  (1.0 s) physical motion and released torque normally. No gripper contact was
  latched, so this validates the short execution/safety path only, not grasp
  success. The Jetson checkpoint remains verified at
  `/home/jetsonl7/robot-data/models/smolvla_fixed_pick_place_1097975_020000`.
  A persistent Hugging Face cache under `/home/jetsonl7/robot-data/cache/`
  removes the former per-container 2.03 GB SmolVLM2 download; rollout is offline
  by default after one preparation command. The cache was populated and an
  offline load reached the arm preflight without any Hub request. Its initial
  calibration failure was diagnosed as an integration bug: setting `HF_HOME`
  redirected LeRobot's calibration lookup as well as the model cache. Rollout
  now sets only the Hub cache variables, preserving the existing read-only
  `/root/.cache/huggingface/lerobot/calibration` mount. The corrected offline
  dry run passed model loading and calibration, then safely stopped because the
  previous 20-step run left `elbow_flex` about 13.6 degrees away from the saved
  folded start. An onsite supervised folded return is the next action. See
  `docs/experiments/smolvla-onsite-handoff-20260908.md`.

- September 7: synthetic SmolVLA GPU forward/backward/inference passed (`1094450`)
  and old ACT data completed 100 training steps with a saved checkpoint (`1094687`).
  Checkpoint reload with held-out episode-24 inference also passed (`1094988`,
  peak 0.93 GiB). All three engineering checks are now closed. Two of eighteen
  decoded action components exceeded the recorded corpus range, including a
  negative gripper position, so any executor must clamp per-joint bounds. This is
  engineering validation, not a new-task success claim or Jetson inference test.

- September 7 long run: a real-step-count training completed on the old ACT data
  (`1097975`, 20,000 steps, batch 32, 01:05:19, exit 0, five 4,000-step
  checkpoints). Loss fell from 0.421 at step 100 to 0.019 with the gradient norm
  decreasing monotonically, and throughput and memory stayed flat for the hour.
  Held-out evaluation `1099226` scored checkpoint `020000` on the same twelve
  frames the ACT v2 holdout used and reported per-joint MAE of 0.329 deg pan,
  0.291 deg lift, 1.048 deg elbow, 0.310 deg wrist flex and 1.315 gripper units,
  roughly three to four times lower than ACT's 1.39 / 1.87 / 3.73 / 1.06 / 4.59.
  This is single-step action error under matched protocol, **not** task success:
  ACT produced inconsistent physical grasps at its own error level. Normalization
  statistics may span the full dataset, so this is not a leakage-free benchmark.
  The dataset carries one task string, so nothing here shows instruction
  following. Jetson latency was measured on 2026-09-08 and passes: end-to-end
  median 1.226 s against the 2.5 s chunk budget, about 2.04x headroom, 0.904 GiB
  peak, in the 25W power mode with nothing else running. The `jp62` image needed
  transformers/tokenizers/num2words/accelerate plus a newer regex, installed with
  `--no-deps` under `/data/tmp` rather than into the image. Action clamping,
  camera-capture cost, concurrent ROS load and checkpoint resume remain
  unverified. Code is on branch `smolvla-longrun`; `main` is untouched. See
  `docs/experiments/smolvla-longrun-20260907.md`. See
  `docs/experiments/smolvla-validation-20260907.md` for paths and action semantics.
  User reports basket transport is infeasible; the intended task now uses arm-held
  transport, which still needs recording and integration validation. Teammates'
  map/navigation commits `046834c` and `8fefd78` are now published and preserved.

- Historical September 6 update: remote-only support prioritized isolated SmolVLA
  training preparation on Roihu while teammates own physical testing. The proposed
  medicine/water delivery task, VR dual-arm recording and carrying method are not
  yet settled or validated; there is no new task dataset. Keep ACT as the baseline.
  See `docs/experiments/progress-20260906.md` for teammate navigation evidence and
  `docs/experiments/smolvla-roihu-setup-20260906.md` for setup/launch instructions.
- Jetson teammate route changes observed on September 6 were unpublished and
  remain untouched. A six-report sofa-to-table PASS was inspected; real VLA
  execution and current public-web motion integration are not verified here.
- At September 6 closeout, Roihu setup installed successfully in the independent `summer-robotics-smolvla`
  root; SmolVLA/training imports passed and both pretrained policy and VLM
  snapshots were cached. GPU smoke is prepared but not submitted, and no new-task
  training has run. See the runbook for exact model revisions. Scratch was near
  its project quota (939G/1.0T before setup); check capacity before uploading data.

## Historical baseline (August 2026; not current deployment instructions)

- On 2026-08-30, manual-push mapping candidate `20260830T095346Z` passed
  299.8 s / 9.68 m at 7.98 Hz with zero tracking loss. Three independent
  camera-only localizations while facing map `-Y` progressed monotonically
  from `(0.083, 0.066, -90.3 deg)` through `(0.078, -0.115, -88.7 deg)` to the
  physically placed table pose `(0.060, -0.372, -86.5 deg)`. The fixed demo
  target is now `(0.060, -0.372, -90 deg)`. Planner-only and operator-observed
  short/longer docking trials passed against the new map. Three subsequent ACT
  attempts were operator-labelled fail, success and near-success; this is not
  a stable success-rate claim.
- `scripts/jetson_nav_then_act_pick_place.sh --auto-demo` now accepts one
  explicit onsite `AUTO_PIPELINE` authorization and then propagates a scoped
  `FORESTBRIDGE_DEMO_ARMED=1` token to the existing gimbal, Nav2 and ACT
  children. It removes only the inner RETURN/PLAN/MOVE/READY/ROLLOUT pauses;
  all existing motion caps, fail-closed exits, active braking and torque-off
  verification remain. The integrated path now folds the white arm before base
  travel, runs ACT only after a successful docking, and performs a final folded
  return after a successful rollout. Physical auto-demo runs on 2026-08-30
  verified docking, ACT execution and final fold; program PASS is not a grasp
  success label. A 0.477 m run passed in 38.658 s and two 0.725 m runs passed
  in 57.083 s and 45.467 s. See `docs/19-machine-handoff-20260830.md`.
- Repeated fixed-scene ACT trials remain inconsistent. Two rapid test sequences
  triggered the unchanged 60°C gripper guard at measured 68°C and 67°C; both
  failed closed with white-arm torque released. Do not raise this threshold or
  retry before cooling. The handoff baseline therefore uses a marked object
  placement and edited successful video evidence rather than claiming robust
  autonomous grasping.

- A 3.5-day demo freeze is active from 2026-08-27: deliver one phone-started,
  observable fixed-scene navigation-to-ACT task before expanding object,
  transport or interaction scope. `tools/forestbridge_task_executive.py` now
  defines the first dry-run-only task/status contract (`status.json` plus
  `events.jsonl`), finite retries, uncertain-result handoff and local Stop
  behavior. No hardware adapter is connected yet. See
  `docs/17-demo-delivery-plan-20260827.md`.
- The first local web vertical slice now passes: `web/relay_server.py` stores
  allow-listed tasks, robot heartbeats and events; the outbound-only
  `tools/forestbridge_robot_worker.py` runs the dry-run executive; and the
  mobile page under `web/static/` creates, stops and renders tasks. Browser QA
  confirmed a complete 20-event task, offline/idle state changes and a 390 px
  mobile layout without horizontal overflow. The opt-in Gemini monitor is now
  connected read-only; ROS, serial and motor interfaces remain disconnected.
  See `docs/18-web-relay-dry-run-20260827.md`.
- The Frankfurt SSH host passed a read-only feasibility check and has Docker,
  Node and Python, but only about 3.6 GiB RAM and no active Tailscale service.
  Treat it as a lightweight HTTPS UI/task relay candidate, never as a robot
  controller or vision-compute host.
- `robot.wichai.xyz` resolves to the Frankfurt host. The authenticated relay
  and Caddy containers are deployed under `/data/projects/forestbridge-relay`;
  relay health passes, Let’s Encrypt certificate issuance succeeded, public
  HTTPS works, unauthenticated state access returns 401 and UI-authenticated
  access succeeds. Public task `4e434ea6a9954f73af676a0ec1dc2517`
  completed 20 events through a local outbound dry-run worker. Real Jetson now
  runs an opt-in, read-only three-camera monitor under
  `/home/jetsonl7/robot-data/services/forestbridge-monitor`: the browser switch
  selects automatic task following, Gemini, white-wrist or black-wrist low-rate
  JPEG snapshots; disabling it removes the server frame, and an active relay
  task pauses independent capture. ACT now reuses the Gemini/white-wrist arrays
  it already reads, while SLAM/Nav2 subscribes to its existing ROS color topic;
  neither task preview opens another physical camera handle. The non-blocking
  publisher, actual-source metadata and a five-second task-frame lease are
  deployed. A no-camera/no-motor synthetic Jetson smoke reached the public
  relay with `owner=task`; physical task-stream continuity remains unverified.
  All three idle-monitor sources produced real public-relay frames. Because user-systemd linger
  requires unavailable sudo credentials, the verified process uses a detached
  watchdog plus user `@reboot` crontab. The task worker, ROS, serial and motor
  adapters remain disconnected.
- On 2026-09-04, the Frankfurt host gained the teammate SSH account
  `forestbridge-dev`. On 2026-09-05, the forced first-login password change
  was removed for mobile SSH compatibility, and the account was granted
  password-required full `sudo` access for the competition. It is not configured
  for passwordless sudo or direct Docker-group access. The password itself is
  intentionally not stored in Git. Remove this temporary account promptly after
  the competition.

- The 2026-08-14 fixed downward-Gemini supervised RGB-D mapping candidate
  `20260814T140025Z` passed at 7.143 Hz with zero tracking loss, a 0.467221 s
  maximum gap, 5.4 cm position closure and 0.71° orientation closure over a
  9.10 m manual route. It is the current RTAB-Map candidate for supervised
  localization/planning experiments, not yet a navigation-grade localization
  source. The fixed reference is raw gimbal ID7=4066/ID8=1924 and the candidate
  config is `configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml`.
  Camera-only localization, overlay export and Nav2 planner-only have since
  passed against this database; a short supervised base motion also passed.
  On 2026-08-23, repeated read-only bus-cadence checks and a raised-wheel
  zero-velocity/torque-off transaction passed, and a grounded 0.04 m/s,
  one-second pulse moved about 5 cm before a verified stop. On 2026-08-24,
  a 1.284 m supervised Nav2 leg near the known map start reached the configured
  7 cm / 8 degree arrival tolerance in 56.488 s; the operator measured about
  1.30 m travel and all three wheels were subsequently read back at zero
  velocity and torque-off. This is a useful long-leg baseline, but the old map
  is not a robust arbitrary-start localization source. A later short table-side
  route exposed a more immediate blocker: during the initial nominal rotation,
  wheel and RGB-D yaw diverged sharply and individual wheel feedback was not
  rotation-consistent, leading to repeated reorientation and reported desk
  contact. Do not loosen limits or repeat table-side motion; add a pure-turn
  consistency abort and validate in open space first. See
  `docs/slam/14-supervised-nav2-long-leg-and-rotation-divergence-20260824.md`.
- Improve the fixed-scene ACT grasp by adding deterministic grasp-success feedback around the current policy.
- Use gripper position/current/load plus the white-wrist RGB stream to distinguish grasp, empty close, slip and jam before allowing transport.
- Keep all robot USB ownership and execution on the onboard Jetson.
- Keep GitHub `main` as the code source of truth; treat `/robot-data/tmp` only as an experiment area.
- Train a separate 28-episode ACT comparison checkpoint while retaining the original 11-episode corpus and step-6,000 checkpoint unchanged.
- Start the laboratory human-interaction track with an offline-only
  YOLO11n-pose and deterministic gesture MVP. Keep it independent from ACT,
  SLAM, base repair and Jetson hardware until recorded-video QA passes; see
  `docs/13-lab-human-interaction-roadmap.md`.

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
- Foreground ACT/Nav2/pipeline entrypoints and the common `scripts/jetson_slam_exec.sh` wrapper announce a local task guard before their first hardware command. The idle camera monitor observes this marker and now actively terminates only its in-flight snapshot subprocess instead of waiting for the 20-second snapshot timeout; a real Jetson lock-held smoke released the foreground task in 1.347 seconds. The task retains a 25-second fail-closed upper bound. A live nested pipeline owns one guard; confirmed stale PID/start-time markers are removed automatically. `scripts/jetson_robot_exec.sh` intentionally remains unguarded because the idle monitor itself uses that lowest-level device wrapper.
- On 2026-09-08 the Gemini idle-monitor warm-up was raised from 5 to 45
  frames. The relay JPEG mean luma improved from about 24.8/255 to 104.8/255.
  The live service copy is under `/home/jetsonl7/robot-data/services/forestbridge-monitor`;
  its previous file is retained as `forestbridge_camera_monitor.py.before-warmup45-20260908`.
  Restarting only the monitor parent during deployment briefly left an in-flight
  snapshot holding `gemini.lock`, causing one 25-second foreground-guard timeout.
  After that snapshot exited, a no-motor guard probe preempted the 45-frame
  monitor and acquired the camera in 4 seconds; no stale task marker remained.
  This snapshot approach is now superseded by the persistent Gemini broker
  below; the measurements remain as diagnosis history.
- Nav2 wheel-mode telemetry now retries each wheel read at most three times with 30 ms spacing. This handles one isolated white-board `communication=-6/-7` without discarding a completed localization, but still brakes and aborts if any wheel fails all three attempts. The 2026-08-28 table test that motivated this change planned a 0.470 m path successfully but produced zero execution samples because motor 7 returned `-7` on the initial measured-velocity read.
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

## 2026-09-08 persistent Gemini RGB-D broker

- Implemented one persistent Orbbec/ROS 2 owner instead of repeated web snapshots.
- The broker fans RGB-D topics out to SLAM/Nav2 and writes a validated atomic RGB frame for the web monitor and ACT/SmolVLA.
- Broker-aware wrappers use host ROS networking and `--external-camera`; if the broker is stale or absent, they fall back to direct camera ownership.
- A healthy broker no longer blocks the foreground task guard. Controller and wrist-camera locks are unchanged.
- Added a motor-free SmolVLA dry-run wrapper. Physical execution still requires `--execute` and on-site emergency-stop supervision.
- Runbook: `docs/ops/gemini-rgbd-broker.md`.
- Deployed the broker without overwriting the teammate's dirty Jetson worktree:
  new repository entrypoints have `broker` in their names, while patched copies
  of the two SLAM container scripts live under
  `/home/jetsonl7/robot-data/services/forestbridge-gemini-broker`.
- Live acceptance: shared RGB stayed fresh at 640×480, the host-network ROS
  consumer read `/camera/depth/image_raw`, and relay frame timestamps advanced
  while SmolVLA was running. No legacy `orbbec_rgb_snapshot.py` process remained.
- SmolVLA broker dry-run exited 0 after loading the checkpoint, consuming shared
  Gemini plus white-wrist RGB, injecting the dataset's exact task string, and
  producing a guarded first action. It explicitly reported that torque/actions
  were not enabled. Log:
  `/home/jetsonl7/robot-data/logs/smolvla-broker-dry-run-task-20260908T1521Z`.
- The broker and web monitor both have `@reboot` launchers. Existing teammate
  home-route files were not edited; use `scripts/jetson_home_route_broker.sh`
  for the broker-compatible table/sofa route until the team merges the change.
- A real Jetson reboot during final audit exercised recovery: Docker initially
  returned one startup-time error, the broker loop retried, and within about two
  minutes both the 640×480 shared stream and live relay frame updates recovered.

## Next Step

1. Start at `docs/ops/team-handoff-20260910.md`; preserve the current teammate
   Jetson work by committing it to its own branch before attempting integration.
2. In a clean clone/worktree, review and merge `origin/smolvla-longrun`. Resolve
   the known overlaps in the hardware wrapper, task guard and SLAM/Nav2 scripts
   rather than overwriting either side.
3. Define `bring_medicine_demo_01` from the September map and current table/sofa
   workspaces. Keep the old web preset motion-locked.
4. Validate the merged tree in this order: no-device/unit tests, SmolVLA dry
   run, Nav2 planner-only, supervised short motion, then an onsite web-triggered
   test with the 12 V cutoff continuously attended.
5. Add calibrated `OBJECT_HELD` and `DELIVERED` checks before presenting the
   workflow as autonomous medicine delivery.
