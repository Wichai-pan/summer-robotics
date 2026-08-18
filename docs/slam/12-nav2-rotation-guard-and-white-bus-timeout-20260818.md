# 2026-08-18: Nav2 rotation guard and white-board bus timeout

## Summary

The supervised camera-only executor now distinguishes rotation from forward
progress. While the commanded linear velocity is zero, visual position change
cannot advance the path waypoint; more than 0.05 m of apparent translation
aborts the run. The first live run of this guard worked as intended, but the
white-board bus then returned `communication=-6` during shutdown and torque-off
could not be verified. The operator cut 12 V. Ground navigation remains
blocked.

The next test is not navigation. It is a read-only, wheels-raised comparison
of low- and high-cadence reads from white-board wheel IDs 7/8/9, with torque
already off. No velocity, torque, mode, EEPROM, camera or ROS write is part of
that diagnostic.

## Evidence

### Previous executor behavior

During the earlier supervised run, the base primarily rotated but camera-only
visual odometry reported changing XY position. The old progress logic accepted
that translation and could advance path waypoints even though the command was
rotation-only. This made a rotation look like forward route progress.

### Rotation-guard run

The guarded run is stored on Jetson at:

`/home/jetsonl7/robot-data/slam/nav2-supervised-execute/20260818T212208Z`

Observed behavior:

- 39 feedback samples over 7.612 seconds;
- commanded linear velocity remained `0.0 m/s`;
- waypoint index remained 3 throughout rotation;
- yaw changed from approximately `-1.74 deg` to `-37.68 deg`;
- visual odometry reported approximately 0.049 m net translation;
- the guard aborted when apparent rotation-only translation exceeded 0.05 m.

This is a successful safety-guard result and a failed navigation result. It
does not prove that the robot physically translated by 5 cm; camera-only pose
change during rotation is exactly the inconsistency being rejected.

### Shutdown failure

After the guard abort, the first brake read succeeded, followed by repeated
white-board failures with `communication=-6`. Zero-velocity and torque-off
were attempted, but final per-wheel torque state could not be read back and
`stop_readback_confirmed` was false. The operator used the physical 12 V
cutoff. Post-test inspection found no residual container, hardware lock or
SLAM/Nav2 process.

The installed Jetson `scservo_sdk` defines `-6` as `COMM_RX_TIMEOUT`: no status
packet was received. The code and logs do not establish whether the cause is
read cadence/half-duplex timing, a common white-board power/data problem, or a
combination of both.

### Read-only follow-up

A subsequent read-only monitor scanned white-board IDs 1-9 in sequence. All
IDs were initially offline, then online, then collectively offline; IDs 6-9
later recovered. Because that probe repeatedly addressed nine devices, it is
not a clean measurement of the three-wheel traffic used by navigation. It does
show that the failure was not isolated to one wheel.

A historical stop diagnostic from 2026-08-15 completed with IDs 7/8/9 at zero
velocity, torque disabled and no shutdown errors. Therefore shutdown readback
can work, but it is not currently repeatable under the tested traffic pattern.

## Software changes

`tools/nav2_supervised_base_execute.py` now:

- freezes waypoint advancement during rotation-only commands;
- aborts on excessive apparent translation during rotation-only control;
- repeatedly broadcasts zero velocity during the braking interval without
  interleaving high-rate per-wheel reads;
- waits for pending bus traffic to settle;
- sends each torque-off write without requesting an immediate status reply,
  then performs a delayed independent register read;
- spaces final torque-off observations by 0.5 seconds;
- still treats any unverified torque-off state as an unsafe shutdown failure.

`tools/base_bus_cadence_diagnostic.py` provides the next isolated diagnostic:

- reads only IDs 7/8/9;
- reads goal velocity, present velocity and torque enable;
- requires three successful torque-off preflight cycles;
- compares a 1.0-second cycle period with a 0.1-second cycle period;
- records every communication result and latency in JSON;
- contains no register-write path;
- delays all hardware imports until after `--dry-run`.

## Current conclusions

Confirmed:

- Nav2 planning is not the direct source of `communication=-6`;
- the rotation-progress bug existed and the new guard stopped it;
- `-6` means that the SDK received no status packet;
- failures affect the common white-board bus, not only one wheel;
- software was previously placing unnecessary read pressure on the bus during
  the safety-critical stop sequence.

Unresolved:

- whether the remaining timeout cause is electrical, connector/power related,
  USB/adapter related, polling cadence related, or mixed;
- whether low-rate reads are fully reliable after the physical wheel and cable
  work;
- whether torque-off writes and independent readback are repeatable after the
  cadence diagnosis;
- whether camera-only feedback is accurate enough for safe route execution.

## Next powered-test gate

Do not run grounded navigation from either the formal deployment or temporary
directory. With all three wheels raised and the operator holding immediate
12 V cutoff access:

1. Temporarily deploy the reviewed diagnostic commit without changing the
   formal Jetson checkout.
2. Run only `base_bus_cadence_diagnostic.py` against the white board.
3. Require torque to already be off on IDs 7/8/9 and zero failures in the
   preflight and low-rate profile.
4. If any low-rate transaction fails, cut 12 V and inspect the shared
   electrical/data path; do not continue to the high-rate or motion tests.
5. If both profiles pass, separately approve a wheels-raised zero-velocity and
   torque-off verification test using the revised shutdown sequence.
6. Restore grounded supervised navigation only after repeated bus and stop
   verification passes. A pass of this bus test does not validate localization,
   planning or physical navigation.

## Read-only cadence result

The approved wheels-raised read-only test passed on 2026-08-18. Its artifact is
stored at:

`/home/jetsonl7/robot-data/slam/base-bus-cadence/20260818T215621Z.json`

- all three preflight cycles reported goal velocity 0, present velocity 0 and
  torque disabled for IDs 7/8/9;
- the low-rate profile completed 90/90 reads with no failure;
- the high-rate profile completed 900/900 reads with no failure;
- the largest register-read latency was 2.052 ms;
- no `communication=-6` or packet error occurred;
- the container exited and the hardware lock was released.

This clears the static torque-off communication gate only. It narrows the
failure toward the write/torque transition, loaded operation, a transient
electrical condition, or their interaction. It does not authorize grounded
motion. The next separate gate is a wheels-raised zero-velocity-only shutdown
transaction test using the revised low-read-pressure sequence.

## Zero-velocity shutdown result

The separately approved wheels-raised shutdown transaction passed. Its
artifact is stored at:

`/home/jetsonl7/robot-data/slam/base-shutdown-sequence/20260818T220222Z.json`

- preflight passed before any write;
- the tool sent eight zero-velocity broadcasts and no nonzero velocity;
- IDs 7/8/9 were briefly torque-enabled only while the zero target was active;
- all three final observations reported goal velocity 0 and torque disabled;
- final signed velocity was 0 for IDs 8/9 and 50 raw for ID 7, within the
  existing stopped-feedback tolerance of +/-60 raw;
- no `communication=-6`, packet error or shutdown error occurred;
- the operator cut 12 V after the test and reported no obvious motor sound;
- wheel rotation was not separately reported and is not inferred from the
  absence of sound;
- the container exited and the hardware lock was released.

This is the first successful live check of the revised low-read-pressure
shutdown sequence. It is evidence that the write/torque transition can
complete, but one pass is not repeatability evidence. Before any grounded
navigation, repeat this exact wheels-raised zero-velocity transaction twice
more. Any timeout, visible wheel rotation, unexpected sound or unverified stop
returns the project to the power/data-path inspection gate.

## Rollback

Keep 12 V off, remove only the temporary diagnostic checkout after artifacts
are copied, and leave `/home/jetsonl7/summer-robotics-deploy` unchanged. The
saved map and prior camera-only SLAM artifacts are unaffected by these changes.
