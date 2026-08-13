# Supervised RGB-D mapping performance rerun

## Scope

On 2026-08-13, the camera-only supervised mapping entry was rerun after the
first local Windows-operated session failed its conservative odometry rate and
gap gates. The test remained a low-speed, manually controlled experiment. It
did not use wheel feedback, IMU fusion, Nav2, autonomous motion, or arm motion.

The tested code was based on `34fd801` with uncommitted changes on
`codex/supervised-slam-cleanup-tuning`. It was temporarily staged at:

```text
/home/jetsonl7/robot-data/tmp/slam-cleanup-tuning-20260813
```

## Changes under test

- `jetson_robot_exec.sh` assigns a unique Docker container name, records its
  ID, and stops that exact container on normal shell exit or a handled signal.
- A detached watchdog also stops the container if the owning host shell is
  killed before its traps can run. It waits for an in-flight Docker launch so
  cleanup does not depend on CID write timing. Fake-Docker tests cover forced
  exit before and after CID creation; a no-device `sleep` container was also
  used to verify the real-Docker path. After `SIGKILL`, Docker and the hardware
  lock disappeared.
- Supervised mapping requests aligned Gemini color and depth at 640x480, 30 Hz.
- Unused camera point-cloud publication is disabled. RTAB-Map still receives
  raw RGB, aligned depth, and camera info.
- Initial and final ROS graph checks retry up to three times to tolerate a
  transient ROS discovery miss. The expected publisher and TF contracts are
  unchanged.
- All existing quality thresholds remain unchanged.

## Intermediate run

Directory:

```text
/home/jetsonl7/robot-data/slam/mapping/20260813T175829Z
```

The RGB-D trajectory itself passed when recovered offline: 119.91 s, 1170
odom/OdomInfo pairs, 9.75 Hz, 0.367 s maximum gap, and zero tracking losses.
The online session remained `INCOMPLETE` because the final fresh `tf2_echo`
subscriber did not discover `odom -> base_link` inside its single five-second
window. This run motivated the bounded graph-contract retry.

## Final passing run

Directory:

```text
/home/jetsonl7/robot-data/slam/mapping/20260813T180346Z
```

| Check | Result | Gate |
| --- | ---: | ---: |
| Duration | 119.842 s | >= 96 s |
| Odom / OdomInfo samples | 983 / 983 | both continuous |
| Odom / OdomInfo rate | 8.194 / 8.194 Hz | >= 5 Hz |
| Maximum message gap | 0.440774 s | <= 0.5 s |
| Tracking losses | 0 | 0 |
| Maximum translation step | 0.0247 m | <= 0.25 m |
| Maximum rotation step | 0.571507 deg | <= 45 deg |
| Maximum estimated speed | 0.246709 m/s | <= 1.0 m/s |
| Median features / inliers | 904 / 421 | diagnostic |
| Estimated path length | 2.821361 m | diagnostic |
| Start-to-end translation residual | about 0.029 m | diagnostic |
| Start-to-end yaw residual | about 1.0 deg | diagnostic |
| ROS graph before/after | PASS / PASS | PASS |

The finalized database is 76.8 MB and contains 146 nodes. Its persisted links
include 12 neighbor links and 27 global-closure links. These database counts
are diagnostic evidence, not proof that every closure is geometrically
correct.

The camera log contains one startup color-decode event (two error lines). The
odometry log contains 150 warnings about dropping queued RGB-D frames. No
tracking loss followed, and the measured output still passed the unchanged
rate and gap gates. Keep both warning counts visible in later comparisons.

After completion, the base reported that wheel torque was disabled and the
serial port was closed. Docker, the global hardware lock, camera processes,
base control, and RTAB-Map processes were all absent.

## Interpretation and next gate

This run validates the guarded manual-control, RGB-D odometry, RTAB-Map mapping,
database-finalization, and cleanup path for a short supervised loop. It does
not make camera-only odometry the formal localization source and does not make
the map ready for navigation.

Before Nav2, continue the planned fused route: confirm read-only wheel feedback
units and Gemini IMU topics, validate low-speed fused `odom -> base_link`, then
run RTAB-Map with that external odometry. Retain this camera-only run as the
health and regression baseline.
