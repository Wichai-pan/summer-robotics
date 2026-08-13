# Algorithm Design: ACT Grasp Contact Supervisor

## Design Context

The ACT checkpoint can reproduce the white-arm pick/place trajectory, but it
has no direct gripper load or current input. Failed trials may therefore keep
requesting closure after the face-cream jar is already between the fingers,
which can end in an ID 6 overload.

Field telemetry on 2026-08-12 established two well-separated regimes:

- empty close: position 5.17--5.24, load 2.4--2.8%, current 0--1 raw;
- jar contact: position 9.22--9.55, load 26.8--28.8%, current 28--44 raw.

The physical white gripper uses larger normalized values for opening and
smaller values for closing. These values are not angles.

## Target Claim

A deterministic side-channel guard can prevent continued gripper tightening
after stable jar contact without changing the trained ACT observation vector
or replacing ACT's arm, lift, and release decisions.

## Design Decision

Prototype a minimal latched state machine around only the gripper command.

## Method Specification

ACT inference and all arm commands remain unchanged. During rollout, read ID 6
`Present_Load` and `Present_Current` in the same process that owns the serial
port. Contact becomes a candidate only while ACT is requesting closure and all
three signals hold:

- normalized position > 7;
- absolute load > 15%;
- current > 15 raw.

After 0.3 seconds of continuous evidence, latch contact and replace further
closing commands by `contact_position - 0.5`. ACT continues to control all
arm joints. A later ACT gripper request >= 20 for 0.2 seconds is interpreted as
deliberate release and clears the latch. A latch lasting over 15 seconds aborts rather
than holding indefinitely.

Temperature and status are checked periodically. Nonzero status, temperature
>= 60 C, or any serial error ends the rollout and triggers existing torque-off
cleanup.

## Assumptions and Invariants

- ID 6 feedback is a supervisor side channel and is not appended to the
  checkpoint observation tensor.
- Only field-verified `v2` gripper telemetry is used for thresholds.
- Contact is not equivalent to complete task success; lift and wrist-camera
  confirmation remain future work.
- The supervisor may prevent further closure but may never invent an arm
  trajectory or an opening command.

## Failure Modes

- A collision with the table can produce load/current like a grasp. Position
  plus later lift/vision confirmation is needed to distinguish it.
- Too small a hold offset may slip; too large an offset may overload. The first
  trial uses the conservative 0.5 normalized-unit default.
- If ACT never requests release, the 15 second hold timeout aborts.
- Serial reads may reduce loop rate; logs must show whether the 20 Hz control
  loop remains practical.

## Ablations and Diagnostics

- Supervisor off: original ACT behavior and overload risk.
- Supervisor on: log latch/release events and `grasp_contact_hold` guard count.
- Compare empty-close and correct-grasp traces; the empty baseline must never
  latch.
- Operator labels remain the task-success authority for the first trials.

## Implementation Handoff

- Modify `tools/act_white_short_rollout.py` with the state machine and telemetry
  log fields.
- Enable it in `scripts/jetson_act_trial.sh` on the experiment branch.
- Add pure unit tests for contact confirmation, empty-close rejection, hold,
  release, and timeout.
- First smoke test: no-motion ACT dry run, followed by one supervised 600-step
  trial with immediate 12 V cutoff available.
- Exit condition: the guard latches on a real jar grasp, never on an empty
  close, releases when ACT opens, and completes without ID 6 overload.
