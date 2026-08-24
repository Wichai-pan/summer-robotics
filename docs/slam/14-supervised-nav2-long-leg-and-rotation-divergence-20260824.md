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

## Next gate

1. Add a fail-closed rotate-only feedback-consistency check before continuing
   any navigation work. It must command zero velocity and perform the existing
   three-wheel brake/torque-off verification on a violation.
2. In clear open space, validate one marked approximately 90-degree turn and
   one short forward segment; compare operator observation, commanded values,
   per-wheel feedback and visual pose without furniture nearby.
3. If that gate passes, select a fixed map-frame docking pose in front of the
   table, run navigation to it, then switch Gemini from the mapping reference
   to the fixed ACT/IK grasp reference before any arm action.
4. Do not relax speed, travel, runtime or visual-disagreement safety limits as
   a substitute for this validation.
