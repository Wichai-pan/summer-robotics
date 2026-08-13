# No-LiDAR fused odometry and RTAB-Map SLAM

## Decision and boundary

The formal base-localization route is:

```text
white-board STS3215 IDs 7/8/9 measured velocity + Gemini IMU yaw rate
  -> robot_localization
  -> /odom and odom -> base_link

Gemini registered RGB-D + external /odom
  -> RTAB-Map mapping, loop closure, and localization
  -> map -> odom
```

This route has no LiDAR, `/scan`, `slam_toolbox`, or simulated laser. The
camera-only `rgbd_odometry` code and its successful 60-second static result
remain a camera-health baseline, not the formal base pose source. Nav2 is
outside this phase and is gated on repeatable map and localization results.

No camera, serial bus, motor, image build, or physical motion was used during
this implementation round. The exact source snapshot was exercised in an
existing Jetson image only as a no-device, disposable-container test.

## Integration with the supervised mapping baseline

The safety fixes proven by the first supervised camera-only mapping session at
`34fd801` have been manually carried into this branch without changing the
formal fused-localization architecture:

- all three wheel goals are cleared in one `GroupSyncWrite` before any wheel
  torque is enabled;
- live wheel commands use one group write instead of three status-producing
  writes, reducing shared-bus traffic;
- shutdown uses no-status zero and torque-off writes and attempts all three
  wheels even after an individual failure;
- terminal control retains a 250 ms dead-man and uses the physically exercised
  mapping limits of `0.04 m/s` and `12 deg/s`, with a 120-second session cap;
- one locked container owns camera, white-board serial, EKF, and RTAB-Map
  lifetime and tears the graph down if a required process exits.

The supervised session proved the camera-only mapping pipeline and these base
control protections. It did **not** verify STS3215 physical feedback units,
Gemini IMU axes, `robot_localization`, or the fused graph. Those remain behind
the gates below.

## STS3215 evidence

| Item | Confirmed value | Use now |
| --- | --- | --- |
| `Present_Position` | address 56, 2 bytes | retain raw in the read-only pilot |
| `Present_Velocity` | address 58, 2 bytes | retain raw in the read-only pilot |
| encoding | sign-magnitude, direction at bit 15 | implemented and tested |
| resolution | 4096 counts/revolution | geometry reference only |
| wheel order | IDs 7, 8, 9 | enforced exactly |

The physical scale of `Present_Velocity` is **unresolved** for the installed
firmware. Feetech examples mention 0.732 rpm/raw, while pinned XLeRobot treats
raw feedback as encoder ticks/s and LeRobot exposes `Velocity_Unit_factor`.
None proves the conversion for these three installed motors. Position behavior
across a complete wheel revolution and stable three-motor read rate are also
unresolved. `configs/slam/sts3215_wheel_feedback_unresolved.json` therefore has
a null physical conversion and every live entry rejects it.

The pinned LeRobot commit is
`22bd7a2f489b367d8df42de803b1e8c4ca63a3f9`; its package version is 0.6.2.
The earlier project description of this source as 0.5.2 is not used as API
evidence.

Primary sources:

- https://github.com/ftservo/FTServo_Arduino/blob/64922cda46e56b21b8c1d9e830d936a1941645ae/src/SMS_STS.h
- https://github.com/ftservo/FTServo_Arduino/blob/64922cda46e56b21b8c1d9e830d936a1941645ae/src/SMS_STS.cpp
- https://github.com/ftservo/FTServo_Python/blob/a203373036723e0d98c6c49b67cf09a9ee299220/scservo_sdk/sms_sts.py
- https://www.feetechrc.com/Data/feetechrc/upload/file/20200611/6372749961523760249976542.pdf
- https://github.com/huggingface/lerobot/blob/22bd7a2f489b367d8df42de803b1e8c4ca63a3f9/src/lerobot/motors/feetech/tables.py

## Gemini IMU contract

The deployed Orbbec ROS 2 v2.8.6 path and project preflight identify:

```text
topic: /camera/gyro_accel/sample
type: sensor_msgs/msg/Imu
frame: camera_accel_gyro_optical_frame
observed rate: about 192 Hz (nominal 200 Hz)
```

The message contains angular velocity and linear acceleration. Its orientation
covariance marks orientation unavailable, so its identity quaternion is not an
absolute attitude or yaw measurement. Moreover, `robot_localization` selection
vectors are expressed in the message frame, and base yaw may not be the optical
frame's Z axis. Every IMU field therefore remains disabled until the read-only
pilot identifies the physical yaw axis and sign. Acceleration and orientation
remain outside the initial candidate.

Sources:

- https://github.com/orbbec/OrbbecSDK_ROS2/blob/v2.8.6/orbbec_camera/launch/gemini_330_series.launch.py
- https://github.com/orbbec/OrbbecSDK_ROS2/blob/v2.8.6/orbbec_camera/src/ob_camera_node.cpp
- `docs/slam/01-jetson-rgbd-bringup-log.md`

## Components and data flow

- `tools/base_odometry_core.py`: ROS-free kinematics, quality gates, and
  midpoint SE(2) integration. It imports wheel geometry and order from
  `tools/base_keyboard.py`.
- `tools/base_wheel_feedback.py`: fake source, unresolved-unit gate, and a
  read-only raw pilot source with delayed SDK import and exact ID whitelist.
  The physical-unit wrapper remains blocked until every pilot gate is filled.
- `tools/base_odometry_ros.py`: hardware-free adapter dry-run and delayed ROS
  boundary. Once verified config exists, live mode reads the whitelisted source
  and publishes `/wheel/odom` without TF. In mapping mode it is also the single
  serial owner: bounded `/cmd_vel` uses the existing kinematics and a 250 ms
  dead-man, while cleanup writes zero and disables wheel torque.
- `tools/base_keyboard_ros.py`: reuses the established terminal input and key
  mapping but only publishes `/cmd_vel`; it never opens the motor bus.
- `configs/slam/ekf_fused_odom.yaml`: planar EKF candidate using wheel `vx`,
  `vy`, and `wz`. Gemini is declared but all fields remain off until yaw axis
  and sign are verified.
- `configs/slam/gemini_imu_unresolved.json`: separate IMU evidence gate. Full
  live mapping is rejected until axis, sign, and covariance are verified and
  exactly the matching EKF angular-velocity field is enabled.
- `scripts/jetson_fused_slam.sh`: host entry. Dry-run starts no Docker process
  and acquires no lock. Future live uses one `--gemini --white` locked session.
- `scripts/slam_fused_mapping_container.sh`: reviewable future full RTAB-Map
  graph using external `/odom`, without `rgbd_odometry`. It remaps the EKF
  output, leaves RTAB-Map `odom_frame_id` empty so the message is consumed, and
  requires a persistent database under `/data/slam/`.

The white-board device is visible to the future container, but
`base_wheel_odometry` is its only reader and writer and accepts only IDs 7/8/9.
The raw pilot performs no writes. A later approved mapping session writes only
wheel goal and torque registers and never addresses white-arm IDs 1-6. It also
refuses a wheel that is not already in velocity mode rather than changing mode
or EEPROM state during a fused-SLAM session.

The mapping launcher keeps `base_keyboard_ros.py` in the foreground as the only
TTY reader; it publishes `/cmd_vel` and never opens the serial port. Every
ROS/camera/mapping backend is monitored; if one exits, the
locked session terminates. The serial owner has a bounded-read-time gate, a
command dead-man, and cleanup that attempts zero plus torque-off for all three
wheel IDs and checks each SDK transmit result even when one cleanup operation
fails. These no-status writes avoid waiting for servo replies; the raised-wheel
test must still verify that the physical stop occurs.
Before torque can be enabled, the launcher also requires a fresh
`sensor_msgs/msg/Imu` sample with the expected frame and unavailable-orientation
marker. A missing/stale IMU therefore cannot silently degrade live mapping to
wheel-only odometry. The pilot sign is evaluated after TF conversion and must
be positive; a negative result remains blocked until the TF or an explicit IMU
adapter is reviewed.

## TF ownership

```text
map --(RTAB-Map)--> odom --(robot_localization)--> base_link
base_link --(static candidate)--> camera_link --(Orbbec)--> optical/IMU frames
```

The wheel adapter publishes `/wheel/odom` but no TF. RTAB-Map subscribes to
`/odom`, publishes `map -> odom`, and does not own `odom -> base_link`.
`configs/slam/fused_slam_graph.json` protects this contract.

## Software-only run

```bash
./scripts/jetson_fused_slam.sh --mapping --dry-run
```

This validates fake feedback, the unresolved hardware gate, candidate camera
transform, and topic/TF ownership. It must not run Docker, map devices, obtain
the hardware lock, import ROS, or import `scservo_sdk`.

The current Jetson `forestbridge-xlerobot:slam-humble` image already contains
the Feetech SDK and pyserial, so Gate 1 can use it without rebuilding. It does
not yet contain `robot_localization`; the reviewed Dockerfile declares that
package, but an image rebuild requires separate approval before Gate 2.

After Gate 1 is separately approved, the read-only pilot entry inside the
single `--white` locked container is:

```bash
python3 tools/base_wheel_feedback.py --pilot --duration 10 \
  --output /data/slam/wheel-feedback/<timestamp>/raw.jsonl
```

It requires typing `READ`, opens only the white serial bus, reads registers 56,
58, 65, 66, and 82, and performs no torque, mode, EEPROM, or goal write.

## Stage gates

### Gate 1: read-only wheel and IMU pilot (next, approval required)

- Input: raised wheels, emergency cutoff, IDs 7/8/9 only, fixed forward gimbal
  raw 4068/1694, synchronized Gemini IMU.
- Output: timestamped raw position/velocity/unit-factor/status and IMU metadata.
  No velocity command is allowed.
- Acceptance: IDs present; sign agrees with hand rotation; scale agrees with
  position difference and timed turns; no stale/missing samples; IMU type,
  frame, and covariance match the contract.
- Rollback: close bus/camera, release the lock, retain the failed log, and leave
  the physical conversion unresolved.

### Gate 2: raised-wheel odometry

- Input: verified conversion and separately approved bounded command session.
- Output: `/wheel/odom`, `/odom`, diagnostics, and TF ownership evidence.
- Acceptance: command/feedback signs match forward, lateral, and rotation; EKF
  remains finite and monotonic; stale/fault stop gates work.
- Rollback: zero wheel goals, stop the session, and return to raw diagnostics.

### Gate 3: low-speed floor odometry and mapping

- Input: reviewed Gate 2, cleared marked route, supervised operator, and the
  camera transform retained as a candidate.
- Output: external-odom RTAB-Map database, loop closures, map and localization
  reports.
- Acceptance: route length/turn behavior is plausible; loop closure aligns the
  start area; each TF has one owner; localization can reopen the map and recover
  from known starts.
- Rollback: stop motion, discard only the failed run, and return to Gate 2.

### Gate 4: Nav2 (not implemented)

Requires repeatable mapping/localization, reviewed footprint and inflation,
validated velocity limits, obstacle sensing coverage, and separate approval.
No Nav2 dependency or launch code is added in this round.

## Human confirmations before Gate 1

1. Approve a read-only locked session that maps Gemini and the white board.
2. Confirm wheels remain raised and can be hand-rotated without moving the
   chassis; keep immediate 12 V cutoff access.
3. Confirm no ACT/arm/base process owns the hardware lock.
4. Confirm the white board still contains wheel IDs 7/8/9 and that IDs 1-6
   must not be addressed.
5. Approve reads of raw registers 56, 58, 65, 66, and 82 plus ROS IMU metadata.
   No EEPROM write, mode change, torque enable, or velocity command is allowed.

Static camera VO passing does not imply wheel odometry, fused odometry, moving
SLAM, loop closure, localization, or Nav2 has passed.
