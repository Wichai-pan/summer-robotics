# Gemini RGB-D SLAM bring-up

## Scope

The first milestone is a supervised, manually driven indoor map made by the
XLeRobot base and its head-mounted Orbbec Gemini 335. It does not include
autonomous navigation, arm motion, ACT/VLA integration, or reuse of the failed
arm eye-to-hand calibration.

Initial stack:

- ROS 2 Humble on Jetson Ubuntu 22.04;
- OrbbecSDK ROS 2 Wrapper v2 with `gemini_330_series.launch.py`;
- RTAB-Map ROS 2 using synchronized RGB and registered depth;
- RTAB-Map RGB-D visual odometry for the first map;
- manual base driving through the existing white-board IDs 7/8/9.

`slam_toolbox` is not the initial mapper because it expects a 2D laser
`sensor_msgs/LaserScan`, and this robot currently has no verified lidar.

Team review documents:

- [中文 bring-up 记录](01-jetson-rgbd-bringup-log.md): decisions, evidence,
  failures, rollback, and the next gate;
- [review checklist](review-checklist.md): repeatable code, container, camera,
  artifact, and merge checks.

## XLeRobot upstream review

The XLeRobot 0.3.0 documentation does not provide a SLAM or mapping bring-up.
Its only ROS 2 note points to an external VR/Rumi integration, so it is not an
implemented XLeRobot navigation stack that can be copied into this project.

The upstream material is still authoritative for the robot-specific layer:

- the official whole-robot keyboard example delegates base commands to
  `XLerobot._from_keyboard_to_base_action()`;
- the project-pinned XLeRobot source at commit
  `3d14695e40c9c68229c0aacffca6053c75cd3eb6` uses wheel radius `0.05 m`, base
  radius `0.125 m`, mounting angles `[240, 0, 120] - 90 degrees`, and the same
  forward/lateral/rotation signs as `tools/base_keyboard.py`;
- the whole-robot example uses `I/K/J/L/U/O` because its other keys control the
  arms; the dedicated base tool intentionally exposes the equivalent motion as
  `W/S/A/D/Q/E`;
- the upstream host configuration has a 500 ms command watchdog; the SSH-only
  base tool uses a stricter 250 ms terminal dead-man timeout;
- the documentation recommends stable camera viewpoints, stable lighting,
  avoiding motion blur, and persistent device naming. These constraints apply
  directly to visual SLAM.

The upstream sensor option is a RealSense D415, while this robot uses an Orbbec
Gemini 335. XLeRobot camera setup commands therefore cannot be copied directly;
the Gemini ROS topics and profiles must be validated through Orbbec's driver.

## Verified baseline

### 2026-08-11 base test

- Host: `jetsonl7-desktop`, Jetson Ubuntu 22.04.5, aarch64.
- White controller serial `5B3D040988` resolved to `/dev/ttyACM0`.
- The shared hardware lock was active and no other hardware container ran.
- The operator raised all three wheels and kept immediate 12 V cutoff access.
- `W/S` forward/back, `A/D` strafe, and `Q/E` rotation all worked in the
  expected direction.
- `Space`, terminal dead-man stopping, and exit cleanup were available.
- The test used the candidate SSH terminal backend in
  `tools/base_keyboard.py`; it has not yet been committed or deployed into the
  Jetson repository.

This verifies the base command path. It does not verify odometry because the
current base controller publishes no wheel encoder odometry or ROS transforms.

### Jetson software baseline

- About 73 GiB storage and 5.1 GiB available memory were observed before the
  SLAM installation.
- ROS 2, Orbbec ROS 2 Wrapper, and RTAB-Map are not currently installed.
- The existing `forestbridge-xlerobot:jp62` image contains the Orbbec Python
  SDK and LeRobot, not a ROS graph.

### 2026-08-11 isolated SLAM image

- Built `forestbridge-xlerobot:slam-humble` as a separate 3.41 GB image; image
  ID prefix `166100ba4347`.
- The existing `forestbridge-xlerobot:jp62` image and host Python environment
  were not modified.
- Installed ROS packages reported by `dpkg-query`:
  - `ros-humble-orbbec-camera` 2.8.6;
  - `ros-humble-orbbec-description` 2.8.6;
  - `ros-humble-rtabmap-ros` 0.23.7;
  - `ros-humble-rosbag2-storage-mcap` 0.15.16.
- The no-device software smoke passed package discovery and verified that the
  Gemini 330 launch exposes depth registration and synchronized IMU arguments.
- The first camera-only preflight did not start because the shared hardware
  lock correctly detected an active supervised ACT rollout. No process was
  stopped and the SLAM container never opened the Gemini.
- A later hardware-alignment attempt identified the Gemini over USB 3.2 and
  started 200 Hz gyro/accelerometer streams, but the current stream profiles
  rejected hardware depth-to-color alignment. The preflight therefore uses
  Orbbec's documented software alignment until a compatible hardware profile
  is measured. This is a recorded compatibility result, not a firmware-update
  authorization.
- The software-alignment rerun passed with 1280x720 RGB8 and aligned 16UC1
  depth in `camera_color_optical_frame`. Its 8.12-second MCAP contained 236 RGB
  frames, 237 depth frames, and 1556 synchronized IMU messages (approximately
  29 Hz RGB-D and 192 Hz IMU). The camera log had no warnings or errors.
- The follow-up no-bag run verified the static camera TF tree from
  `camera_link` through depth, color, and synchronized accel/gyro optical
  frames. It exited cleanly and released the global hardware lock.

## Required frame contract

The initial graph must use these frame roles consistently:

| Frame | Meaning |
| --- | --- |
| `map` | RTAB-Map global frame |
| `odom` | Continuous local visual-odometry frame |
| `base_link` | Robot base reference frame |
| `camera_link` | Rigid Gemini body frame published by the Orbbec wrapper |
| camera optical frames | Published by the Orbbec wrapper |

The Gemini head gimbal must remain at one marked, repeatable pose for an entire
mapping run. The first milestone uses a measured static
`base_link -> camera_link` transform. Moving the gimbal without publishing its
joint state and dynamic transform invalidates the map.

## Phased bring-up

### 0. Base command path

- Input: raised robot, white controller, SSH terminal controller.
- Output: verified six-direction manual control and fail-safe stop.
- Acceptance: all directions are correct and stopping is immediate.
- Rollback: cut 12 V, stop the container, leave wheel torque disabled.
- Status: passed on 2026-08-11.

### 1. Install and camera-only ROS preflight

- Input: approved ROS 2/Orbbec/RTAB-Map container build, Gemini connected by
  USB 3, no motor device mapped.
- Output: timestamped RGB, registered depth, camera info, IMU topics, and a
  valid camera TF tree.
- Acceptance: stable topic rates, matching RGB/depth dimensions and timestamps,
  valid depth scale, no duplicate camera owner, and a saved short rosbag.
- Rollback: stop and remove only the new SLAM container/image; retain the
  existing Jetson image and data.

Build and software-only verification use a separate image name:

```bash
docker build -f deploy/slam/Dockerfile \
  -t forestbridge-xlerobot:slam-humble .
./scripts/jetson_slam_software_smoke.sh
```

The smoke command maps no host path, camera, or motor. After it passes, the
camera-only preflight is:

```bash
./scripts/jetson_slam_camera_preflight.sh
```

That command reuses `jetson_robot_exec.sh`, its Gemini resolver, `/data` mount,
and global hardware lock. It exposes no controller serial device. Artifacts are
written under `/home/jetsonl7/robot-data/slam/preflight/<UTC timestamp>/` and
must remain outside Git.
- Status: passed for camera-only static visual odometry on 2026-08-11 with
  software-aligned depth, synchronized IMU, camera-internal TF, and an
  8.12-second MCAP. Bag analysis found a 0.160 ms maximum RGB/depth timestamp
  delta, and live QA confirmed one camera publisher with approximately 28.9 Hz
  RGB, 26.6 Hz depth, and 197 Hz IMU reception. One shared 0.25--0.27 second
  stream stall remains recorded as a risk. A measured target must still confirm
  physical depth accuracy before navigation or metric map acceptance.

### 2. Static visual-odometry test

- Input: fixed gimbal and camera-only ROS graph. This diagnostic may use
  `camera_link` directly; the base-to-camera transform is not required while
  the base remains stationary.
- Output: RTAB-Map RGB-D odometry while the stationary robot is gently observed
  and the camera view is checked.
- Acceptance: stationary pose remains stable; no repeated odometry loss; TF has
  exactly one owner for each transform.
- Rollback: stop RTAB-Map and retain the diagnostic bag/database outside Git.

### 3. Supervised initial map

- Input: cleared low-speed route, on-site operator, manual base control,
  validated RGB-D odometry.
- Output: RTAB-Map database plus exported 2D occupancy grid and 3D cloud.
- Acceptance: loop closure succeeds, the start area aligns on return, walls and
  major obstacles are recognizable, and no unsafe base behavior occurs.
- Rollback: stop with `Space`/`X` or cut 12 V; discard only the failed run and
  return to the camera-only graph.

### 4. Robustness work, later

Add wheel encoder odometry and evaluate Gemini IMU fusion only after the first
RGB-D map is reproducible. Navigation, localization-only mode, and autonomous
motion are separate milestones requiring their own safety review.

## Current approval boundary

The separate ROS 2 Humble SLAM image build was approved and completed without
mutating `forestbridge-xlerobot:jp62`, the LeRobot environment, calibration
files, or the Jetson host Python installation. The next physical gate is to fix
and mark the camera gimbal before the camera-only static odometry test. Physical
depth accuracy and the measured `base_link -> camera_link` mounting transform
remain mandatory before supervised moving-map acceptance, but do not block the
stationary diagnostic. Do not start visual odometry, change firmware, or move
the base without separate operator confirmation.

Official references:

- XLeRobot 0.3.0 documentation: https://xlerobot.readthedocs.io/zh-cn/latest/
- XLeRobot whole-robot teleoperation:
  https://xlerobot.readthedocs.io/zh-cn/latest/software/getting_started/XLeRobot_teleop.html
- Orbbec ROS 2 Wrapper: https://github.com/orbbec/OrbbecSDK_ROS2
- RTAB-Map ROS 2: https://github.com/introlab/rtabmap_ros
- ROS 2 Humble `slam_toolbox`: https://docs.ros.org/en/humble/p/slam_toolbox/
