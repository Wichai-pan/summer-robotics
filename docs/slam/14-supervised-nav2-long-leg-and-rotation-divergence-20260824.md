# 2026-08-24: supervised Nav2 long-leg result and rotation divergence

## Scope

This session used the existing downward-Gemini map
`/data/slam/mapping/20260814T140025Z/rtabmap.db`, a fixed gimbal reference
(black-board ID 7 raw 4066, ID 8 raw 1924), an on-site operator and immediate
12 V cutoff. The base was controlled only after the `MOVE` confirmation. The
map database was read-only. These results do not validate arbitrary-start
global localization because the room and map are no longer contemporaneous.

## Long supervised navigation passed

The route to `(x=1.200 m, y=-0.461 m, yaw=0 degrees)` planned at 1.284 m and
ran with wheel-feedback control, 0.04 m/s linear and 12 deg/s angular caps,
1.50 m tracked-travel cap, and 80 s runtime cap. The run saved to
`/data/slam/nav2-supervised-execute/20260824T141037Z`.

- The initial map-frame pose was `(0.016, -0.009, -1.87 degrees)` and the
  planner path-start check was 2.49 cm.
- The executor reported `goal_position_and_yaw_reached` after 56.488 s at
  `(1.1542, -0.4179, -7.23 degrees)`, 6.29 cm from the configured goal with a
  7.23 degree final-yaw error. Both values are inside the configured 7 cm / 8
  degree arrival tolerance.
- The on-site operator measured approximately 130 cm of physical travel,
  consistent with the 128.4 cm planned path.
- The active zero-velocity brake and all three torque-off readback samples
  passed: each wheel had goal velocity 0, present signed velocity 0 and torque
  enable 0. No map re-localization was applied during the run.

This is a repeatable-component result for a supervised leg launched near the
known map start. It is not a claim that the old map supports reliable global
relocalization or obstacle avoidance in a changed room.

## Table-side route failed safely

A later route targeted `(-0.250, -0.411, -90 degrees)`, planned at 0.518 m,
with a 35 s runtime cap. It stopped because the runtime cap expired; brake and
torque-off verification still passed. The operator reported that the base
turned through the wrong physical area and contacted the desk. The route must
not be repeated near furniture until its rotation gate is corrected.

The saved trace is
`/data/slam/nav2-supervised-execute/20260824T152609Z/nav2-execution-report.json`.
It shows a control-state inconsistency during the initial nominal rotation:

| elapsed | wheel-integrated yaw | RGB-D yaw |
| --- | ---: | ---: |
| 5.008 s | -53.84 degrees | -4.75 degrees |
| 10.016 s | -88.64 degrees | -44.18 degrees |
| 20.035 s | -120.61 degrees | -88.53 degrees |
| 30.051 s | -169.33 degrees | -142.60 degrees |

During nominal rotate-only portions, feedback also became nonuniform; for
example at 8.013 s the signed raw feedback was ID7=-600, ID8=-150 and
ID9=+200. A symmetric turn command should not be accepted as healthy when a
wheel reports the opposite sign. The controller currently prefers wheel pose
while rotating to avoid known RGB-D false translation; it consequently kept
trying to recover an off-path state and progressed toward an unsafe physical
area. This evidence does not yet identify whether the primary cause is motor
response, wheel slip, feedback semantics or visual-yaw error; it does prove
that the current rotate-only condition is insufficient.

## Implemented software gate (2026-08-25)

Commit `379f2bb` applies the pre-existing `max_rotate_translation_m` bound to
wheel-feedback control as well as RGB-D-only control. A rotate-only command
whose current control pose drifts farther than 5 cm from its rotation anchor
now raises an error before later path correction can steer toward furniture;
the existing active zero-velocity brake and three-wheel torque-off readback
remain the common exit path. The targeted Jetson-container tests
`test_nav2_rotation_progress_guard.py` and `test_nav2_wheel_feedback_control.py`
passed 20 tests without mapping hardware devices. This has not yet been
physically validated and does not by itself establish the faulty sensor or
wheel.

`tools/base_turn_diagnostic.py` adds a separate open-space test that does not
load the map or command Gemini/arm motors. It commands only IDs 7/8/9 for one
bounded 5--90 degree turn, records their present-velocity integration, applies
the same 5 cm rotate-only drift guard, and then uses the verified brake and
torque-release transaction. It is intended to test 30 degrees first and 90
degrees only after the small physical test is correct.

### Floor-reference yaw calibration (2026-08-25)

With the chassis manually aligned to a tape start line, left and right tests
each accumulated 90 degrees plus 30 degrees of wheel-feedback target and
ended at approximately the same physical 90-degree tape reference. The
observed chassis-yaw-to-feedback ratio is therefore provisionally `0.75`.
The executor applies this only to the wheel pose tracker's yaw integration
through the bounded `--wheel-yaw-scale` option (default `0.75`); it does not
raise motor speed or relax any guard. This requires a subsequent supervised
route test before it can be treated as a navigation result.

### Corrected short-route result (2026-08-25)

The corrected 0.625 m route started with wheel and visual heading in close
agreement (at 7.4 s: wheel `-28.26` degrees, visual `-28.08` degrees), so the
yaw calibration did not cause the stop. During the subsequent translation, the
old-map visual pose exceeded the 12 cm wheel/visual re-localization threshold.
The required 3 s visual settle had a spread of 8.6 cm and 9.2 degrees, above
the 4 cm/6 degree acceptance bound, so the executor safely braked and released
all wheels. For a clearly supervised, short, obstacle-free wheel-control
experiment, `--wheel-visual-policy liveness` keeps fresh RGB-D and initial
map-pose requirements but records rather than applies that unstable old-map
translation correction. The default `bounded` policy is unchanged.

## Next gate

1. In clear open space, validate the new rotate-only 5 cm drift guard while
   performing one marked approximately 90-degree turn and
   one short forward segment; compare operator observation, commanded values,
   per-wheel feedback and visual pose without furniture nearby.
2. If that gate passes, select a fixed map-frame docking pose in front of the
   table, run navigation to it, then switch Gemini from the mapping reference
   to the fixed ACT/IK grasp reference before any arm action.
3. Do not relax speed, travel, runtime or visual-disagreement safety limits as
   a substitute for this validation.

## Table docking mode (2026-08-25)

The 2026-08-25 table-edge trace against the newer manual-push map reached a
state near `(0.16, -0.32, -151 degrees)` while its configured table goal was
`(0.052, -0.357, -90 degrees)`. It was still about 11 cm from the goal, so this
was not a successful arrival followed by an unnecessary final-yaw correction.
The legacy follower had no lateral command: with an X error beside the table it
kept turning toward the final path point, which is not acceptable near furniture.

`tools/nav2_supervised_base_execute.py` now has an **opt-in** docking mode:

- `--dock-entry-distance-m M` is disabled at `0` (the default), preserving
  existing supervised-nav behaviour. When enabled, it defines the clearance
  radius at which the base stops ordinary path following and aligns to the
  configured goal yaw.
- After alignment, it converts the remaining map-frame XY error into the
  holonomic base frame and commands forward/backward plus lateral translation
  with zero angular velocity. It logs `body_vx_mps`, `body_vy_mps` and
  `dock_phase` in the execution report.
- If yaw exceeds `--dock-yaw-align-tolerance-deg` during final translation,
  it pauses translation, re-enters the explicit goal-yaw alignment state, and
  then resumes the same holonomic approach. This is deliberately different
  from the ordinary path follower's turn toward a map waypoint: docking only
  turns to restore the front edge parallel to the configured table-facing yaw.

The first physical use must start with a generous entry radius in a clear
approach corridor and a short table-free validation of lateral direction. It
does not authorize pressing the base into a table; the final base pose must
still leave room for the arm and its safety clearance.

The wrapper exposes `--position-tolerance-m` (default `0.07`) so a confirmed
table docking pose can explicitly tighten its final XY arrival gate, for
example to `0.025`. This changes only when the controller declares arrival; it
does not silently change map coordinates or the default supervised-navigation
behaviour.
