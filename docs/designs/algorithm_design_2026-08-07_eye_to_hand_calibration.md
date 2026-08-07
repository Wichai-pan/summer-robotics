# Algorithm Design: Black-arm RGB-D Eye-to-hand Calibration

## Design Context

The simulated XLeRobot IK produces geometrically meaningful joint angles, but
the real black arm uses a different encoder convention and the real Gemini 335
mount differs from the simulated camera pose. Directly executing simulation
angles therefore failed to place the gripper above the detected face-cream jar.

Nine stationary samples pair the Gemini-aligned RGB-D location of a pale-blue
marker held by the gripper with the five measured real-arm encoder angles.

## Target Claim

Estimate a real camera/arm geometric model that predicts a held-out marker
location from real encoder angles. This first fit is diagnostic and does not
authorize physical motion.

## Design Decision

`prototype`: fit the smallest URDF-constrained model, reserve one spatially and
kinematically distinct sample as a holdout, and keep all generated calibration
artifacts motion-locked.

## Problem Formulation

- Input: real measured encoder vector and a fixed SO101 URDF chain.
- Observation: aligned RGB-D marker centre in the Gemini color optical frame.
- Output: joint direction convention, identifiable joint zero offsets, marker
  point in the fixed-jaw frame, and camera/arm rigid transform.
- Evaluation: Euclidean prediction error on an unused ninth sample.

## Method Specification

For sample `i`, the predicted point is

```text
p_camera_i = T_camera_from_arm_base * FK_URDF(q_i) * p_marker_in_jaw
```

The five joint signs are enumerated. Lift, elbow, and wrist-flex offsets and the
three-dimensional marker point are optimized with robust nonlinear least
squares. For each proposal, the best camera rigid transform is recovered with
Kabsch alignment.

Shoulder-pan offset is fixed because it is inseparable from free camera
rotation. Wrist-roll offset is fixed because it is inseparable from rotation of
the unknown marker point. These are coordinate gauge choices, not claims that
the physical offsets are zero.

## Assumptions and Invariants

- The base, Gemini mount, cream jar, and gripper attachment did not slip during
  sample collection.
- The URDF link geometry is representative of the real arm.
- `MEASURED_ENCODER_JSON`, not legacy P-controller targets, describes geometry.
- The fitter never opens camera, serial, or motor devices.
- Its output always contains `motion_locked: true`.

## Relation to Baseline and Prior Work

The teammate's analytic IK and URDF geometry remain unchanged. This adds the
missing physical encoder convention and eye-to-hand extrinsic calibration.

## Failure Modes

- Low training error and high holdout error: overfit, URDF mismatch, marker
  movement, or insufficient excitation; collect targeted samples or revise the
  model.
- High training error: bad pairing, wrong arm chain, RGB-D outlier, or non-rigid
  marker attachment.
- Multiple equally good joint-sign models: positional data alone is ambiguous;
  use known motor direction or an additional controlled motion diagnostic.
- A good positional fit does not validate command targets or collision safety.

## Ablations and Diagnostics

- Hold out the ninth multi-joint/roll sample.
- Report per-training-sample errors, total RMSE, and held-out error.
- Compare the best discrete sign convention with runner-up training errors.
- Later repeat one pose to measure RGB-D plus encoder repeatability.

## Implementation Handoff

- Scope: offline calibration only.
- File: `tools/fit_black_arm_eye_to_hand.py`.
- Inputs: URDF and `calibration/black_arm_eye_to_hand_samples.jsonl`.
- Output: `calibration/black_arm_eye_to_hand_fit.json`.
- Smoke test: fitter completes deterministically and emits a rigid 4x4 transform.
- Exit condition: continue only if held-out error is acceptable and repeated-pose
  tests confirm stability; otherwise revise/collect targeted data.
- Coding must not silently enable physical execution or convert the result into
  legacy P-controller commands.

## Experiment Handoff

First gate: held-out Cartesian error below 20 mm. This is only a provisional
geometry gate. Physical IK additionally requires command-coordinate validation,
workspace limits, a high-waypoint dry run, and supervised low-speed execution.

## Project Memory Writeback

The previous simulation-extrinsic direct execution is retained as a negative
result. This calibration is a diagnostic attempt to close the measured
sim-to-real geometry gap, not a completed grasping result.
