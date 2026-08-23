# 2026-08-23: base stop verification and wheel-feedback Nav2

## Scope

This session continued supervised navigation against the fixed downward-Gemini
map, with an on-site operator, cleared route and immediate 12 V cutoff. It did
not authorize autonomous operation, a faster base, or a larger operating area.
The map database remained
`/data/slam/mapping/20260814T140025Z/rtabmap.db`; the gimbal was returned to
the mapping reference (ID 7 raw 4066, ID 8 raw 1924) before motion.

## What passed

- Two read-only white-board cadence checks completed all low- and high-rate
  reads for wheel IDs 7/8/9 without a communication error.
- Raised-wheel zero-only shutdown checks passed. A transient idle feedback of
  `-50` raw on ID 8 was rejected once and then cleared on a repeat; this is
  inside the configured stopped-feedback tolerance but is retained as evidence
  that a single preflight sample can be noisy.
- A grounded `0.04 m/s` forward diagnostic for one second moved the robot about
  5 cm by ruler observation. The later repeat confirmed zero goal velocity,
  zero signed present velocity and torque disabled for all three wheels after
  the active braking interval.
- The new measured-wheel controller completed a 0.214 m planned route in
  `/data/slam/nav2-supervised-execute/20260823T190936Z`. It reported
  `goal_position_and_yaw_reached` after 17.827 s, with final wheel estimate
  6.34 cm from the goal and 7.56 degrees heading error, both within the
  configured 7 cm / 8 degree arrival tolerances. Its stop readback succeeded.

## Controller decision and code state

`tools/nav2_supervised_base_execute.py` now anchors a local wheel-feedback pose
to a fresh `map -> odom -> base_link` observation, integrates the three
`Present_Velocity` readings at 5 Hz, and commands only wheel IDs 7/8/9. RGB-D
is still required for stream liveness and remains an independent translation
disagreement guard; it is no longer the sole high-rate progress signal. The
executor retains the double `MOVE` confirmation, velocity/travel/runtime caps,
active zero-velocity braking, and final torque-off readback.

The route follower also preserves the initial Nav2 waypoint and uses an ordered
0.10 m lookahead steering point. This avoids treating a small first grid-cell
kink as a large heading target. The relevant deployed commits are `ebc1628`,
`b65e348`, `81377d1`, `c0d8f81`, `eb6d368`, and `e5275a6`; the Jetson container
passed 23 targeted unit tests at `e5275a6`.

## Long-route result and current blocker

The first long route (`20260823T191528Z`) was stopped by wheel/RGB-D
translation disagreement of 0.343 m. After lookahead steering was added, the
repeat in `/data/slam/nav2-supervised-execute/20260823T192228Z` planned 0.598 m
to `(0.550, -0.311, 0 degrees)`. It began with a right turn and then progressed
forward/diagonally in the path direction rather than repeating the earlier
left-right correction. Around 10.6 s, the wheel estimate was approximately
0.33 m from its start and 0.284 m from the goal. The run then stopped safely
when a visual update produced 0.379 m wheel/RGB-D translation disagreement,
above the 0.200 m limit. The stop was confirmed with no shutdown error.

This is neither a goal-reached result nor proof that the visual pose is wrong:
the saved trace must distinguish a one-sample RGB-D outlier from genuine
wheel/visual drift. It is unsafe to increase the disagreement threshold, route
length or speed before that distinction is made.

## Next gate

1. Plot/review the wheel and RGB-D pose series from the latest execution report
   and identify whether the guard was triggered by an abrupt visual jump or a
   persistent divergence.
2. Add and unit-test a temporal robust-consistency rule or a properly bounded
   fusion update. It must still stop on persistent disagreement and retain the
   existing serial, active-brake and torque-off verification.
3. Repeat the same 0.598 m route with the same map/gimbal reference and compare
   physical displacement, wheel estimate and visual estimate before attempting
   a longer route.
