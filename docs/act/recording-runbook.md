# Fixed Pick-and-Place ACT Recording Runbook

This runbook records one complete successful episode per process invocation:

```text
fixed folded pose -> fixed pick -> fixed place -> fixed folded pose
```

The black arm is a torque-free leader.  The white arm is the follower and the
future ACT-controlled robot.  ACT inputs are Gemini RGB, white-wrist RGB, and
white-arm state.  The action is the command actually sent to the white arm.
Black-leader state and tracking error are diagnostics only.

The recorder was validated against pinned LeRobot commit
`22bd7a2f489b367d8df42de803b1e8c4ca63a3f9` (0.6.2). Rebuilding with an
unpinned `external/lerobot` checkout invalidates this environment record.

## Gates Before Motion

1. Confirm no teammate owns Gemini or either controller.
2. Fix and photograph the table, Gemini mount, both arm bases, lighting,
   cream start marker, place marker, and folded pose.
3. Assign a scene version such as
   `facecream_white_fixed_pick_place_v1_20260810`.
4. Use the verified white-wrist mapping: host path `2.4.1`, wrapper
   `--wrist-a`, container `/dev/wrist-2-4-1`. Path `2.4.3` is the black wrist;
   `/dev/videoN` is forbidden.
5. Pass the no-hardware dataset smoke and the camera-only smoke before mapping
   motor devices.

## No-Hardware Dataset Smoke

After rebuilding the Jetson image, run without USB flags:

```bash
cd /home/jetsonl7/summer-robotics-deploy

./scripts/jetson_robot_exec.sh -- \
  python3 tools/act_dataset_smoke.py \
  --root /data/act-smoke/$(date +%Y%m%dT%H%M%S)/dataset
```

Acceptance output contains:

```text
PASS create -> save_episode -> finalize -> reopen
episodes=1 frames=10 fps=10
```

## Camera-Only Smoke

The 2026-08-10 validation ran this once per wrist without mapping a motor. Both
streams delivered 60/60 unique samples at 640x480 MJPEG/30 FPS with maximum
frame age below 30 ms. The fixed edge blemish confirmed wrist A as white.

```bash
./scripts/jetson_robot_exec.sh --gemini --wrist-a -- \
  python3 tools/act_camera_smoke.py \
  --white-wrist-device /dev/wrist-2-4-1 \
  --output-dir /data/act-smoke/wrist-a

./scripts/jetson_robot_exec.sh --gemini --wrist-b -- \
  python3 tools/act_camera_smoke.py \
  --white-wrist-device /dev/wrist-2-4-3 \
  --output-dir /data/act-smoke/wrist-b
```

## One Supervised Episode

Use the verified white-wrist pair `--wrist-a` and `/dev/wrist-2-4-1` together.

Once, put the torque-free white arm in the chosen folded pose and save its
reference. This command maps no camera and never enables torque:

```bash
cd /home/jetsonl7/summer-robotics-deploy

./scripts/jetson_robot_exec.sh --white --interactive -- \
  python3 tools/save_white_folded_pose.py \
  --robot-id white_arm_leader_follow \
  --output /data/act/config/white_folded_pose_v1.json
```

Review the printed joint values, then enter `SAVE`. Keep this JSON unchanged
for dataset v1; changing it creates a new scene/dataset version.

```bash
cd /home/jetsonl7/summer-robotics-deploy

./scripts/jetson_robot_exec.sh \
  --gemini --wrist-a --black --white --interactive -- \
  python3 tools/black_leads_white_wrap_safe.py \
  --white-id white_arm_leader_follow \
  --full-range \
  --duration-s 120 \
  --fps 20 \
  --max-speed-deg-s 30 \
  --max-gripper-speed-s 60 \
  --record-root /data/act/fixed_pick_place_v1 \
  --record-repo-id forestbridge/fixed-pick-place-v1 \
  --scene-version facecream_white_fixed_pick_place_v1_20260810 \
  --white-wrist-device /dev/wrist-2-4-1 \
  --folded-pose-json /data/act/config/white_folded_pose_v1.json \
  --record-width 640 --record-height 480 --camera-fps 30
```

Operation:

1. With torque off, put the white arm at the saved folded pose and the black
   arm in a physically similar pose. The program refuses to record if the
   white start differs from the reference by more than the configured
   tolerance.
2. Type `FOLLOW` only after both camera adapters report ready.
3. Move the black leader through the entire pick-and-place demonstration.
4. Return the black leader, and therefore the white follower, to the fixed
   folded pose.
5. Press `q`.
6. The program numerically verifies the white arm returned to the saved folded
   pose. A mismatch automatically discards the episode.
7. Enter `SUCCESS` only if the complete objective succeeded without collision,
   drop, stale video, timeout, or operator recovery.  Any other answer discards
   the episode buffer and records only a failure ledger row.

Every accepted invocation finalizes the dataset and immediately reopens it.
Do not collect the main corpus until 3 pilot episodes have been visually and
numerically inspected.
