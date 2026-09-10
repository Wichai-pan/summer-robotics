# Persistent Gemini RGB-D broker

## Purpose

Gemini has one physical owner. That owner publishes one RGB-D stream to all
consumers instead of letting the web monitor, SLAM, and VLA compete for USB.

```text
Gemini 335
  -> persistent Orbbec ROS 2 driver
       -> RGB + depth + camera_info -> RTAB-Map / Nav2
       -> RGB subscriber -> atomic JPEG in /dev/shm/forestbridge-gemini
                              -> web monitor
                              -> ACT / SmolVLA observation adapter
```

The web monitor never opens Gemini in this mode. Stopping or refreshing the
web page therefore cannot interrupt a robot task. SLAM containers join the
host ROS network and pass `--external-camera`; they do not launch a second
Orbbec driver. The SmolVLA wrapper requests only the wrist camera and white
controller, and reads Gemini through the shared-frame adapter.

## Health and fallback

The broker is healthy only while its ready file and both shared-frame files
exist, and the frame metadata is no more than three seconds old. Broker-aware
SLAM wrappers fall back to direct Gemini ownership when that check fails. They
never silently consume a stale web frame.

## Commands

Foreground broker diagnosis:

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_gemini_rgbd_broker.sh
```

Motor-free SmolVLA dry run:

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_smolvla_white_rollout.sh
```

Broker-compatible home routes (the existing teammate scripts are preserved):

```bash
FORESTBRIDGE_DEMO_ARMED=1 bash scripts/jetson_home_route_broker.sh table-to-sofa
FORESTBRIDGE_DEMO_ARMED=1 bash scripts/jetson_home_route_broker.sh sofa-to-table
```

Physical execution remains explicit and requires an on-site emergency-stop
operator:

```bash
bash scripts/jetson_smolvla_white_rollout.sh --execute
```

This removes camera contention only. White-board, black-board, and wrist
camera locks remain exclusive, and the broker never commands a motor.

## 2026-09-08 deployed validation

- Shared RGB: 640×480 and continuously fresh.
- ROS: an independent no-device container consumed a 640-pixel-wide depth frame.
- Web: relay frame timestamps advanced during SmolVLA model loading/inference.
- SmolVLA: dry-run exited 0, produced a guarded first action, and sent no action.
- Legacy repeated Orbbec snapshot processes: zero after migration.
- Existing teammate scripts: untouched; broker-specific replacements were
  added alongside them because the Jetson worktree contains uncommitted work.
- Reboot recovery was observed on the real Jetson: both cron launchers returned,
  the broker retried while Docker initialized, and RGB-D plus web frames became
  live again without manual camera intervention.
