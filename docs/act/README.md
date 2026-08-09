# Fixed-Scene ACT Route

## Scope And Baseline

This branch develops an ACT baseline for one narrow task only: the black
SO-101 arm picks the shallow blue face-cream jar from the fixed desk-edge
scene, lifts it clear of the desk, and holds it. The mobile base, Gemini
gimbal, desk, black-arm base, lighting, jar type, and start pose are treated
as controlled scene variables.

This is an ACT-only branch. It deliberately contains no VLA experiments or
VLA-specific model code. The dataset contract below uses standard
LeRobotDataset names and a stable natural-language task string so the
recorded data can be reused by a later VLA branch without a format migration.

Baseline evidence and constraints:

- The fixed-scene manual grasp and supervised replay are verified in
  `docs/06-rgbd-grasp-bringup.md`.
- Jetson is the only runtime hardware owner. Every hardware command goes
  through `scripts/jetson_robot_exec.sh` and its shared lock; calibration is
  mounted read-only. See `docs/07-jetson-deployment.md`.
- `calibration/black_arm_eye_to_hand_fit.json` has
  `status: diagnostic_only`, `motion_locked: true`, and a 93.41 mm held-out
  error. It is forbidden as an execution transform.
- `tools/arm_keyboard.py black --terminal` is the current verified manual
  controller. It preserves the controller convention used by the successful
  replay. It is not yet a `lerobot-record` teleoperator and does not itself
  write a dataset.

## Phase 0 Decision Record

Status: confirmed on 2026-08-09.

- **Task:** pick the shallow blue face-cream jar from the fixed desk-edge
  scene with the black arm, lift it clear of the desk, and hold it.
- **Success rule:** the intended jar is secured, visibly clear of the desk,
  and held for a predeclared duration without collision or an operator
  recovery. A drop, wrong target, collision, stale camera stream, or
  interrupted trial is a failure.
- **Dataset boundary:** every accepted demonstration uses the task string,
  six-joint state/action convention, one fixed Gemini RGB feature, and
  episode-level metadata defined below. Any feature, timing, or scene-hardware
  change creates a new dataset version.
- **Exclusions:** no VLA experiment code, autonomous pick script, deployment,
  or use of the diagnostic eye-to-hand fit belongs to this Phase 0 baseline.

Phase 1 may verify these decisions against the live hardware, but may not
silently change them. A material change returns the route to Phase 0 and
updates this record before data collection begins.

## Dataset Contract

The first ACT dataset is one task, one robot, one camera schema, and one
control convention. Do not silently add or remove features midway through a
dataset version.

| Item | First ACT contract |
|---|---|
| Dataset format | LeRobotDataset, version reported by the installed Jetson container |
| Task string | `Pick up the blue face-cream jar from the fixed desk-edge scene with the black arm.` |
| Observation state | `observation.state`: six black-arm joint positions in the same calibrated LeRobot convention used for actions |
| Action | `action`: six black-arm commanded joint positions, same ordered names and units as the follower robot |
| Vision | `observation.images.gemini_rgb`: one fixed Gemini RGB stream; resolution, FPS, exposure and mount pose recorded in dataset metadata and the session log |
| Episode unit | Reset scene -> approach -> close -> lift -> hold -> supervised return/reset; never splice episodes |
| Labels outside tensors | episode ID, operator, scene version, jar start-cell, result, failure reason, and reset notes in the session ledger |
| Data location | Jetson `/home/jetsonl7/robot-data/act/`; Git stores only configs, schemas, QA reports and manifests |

The Gemini depth stream may be saved as a separate diagnostic artifact, but is
not an ACT input for the first baseline. This keeps the training feature set
small while retaining a stable RGB/state/action contract usable by later
policies. A future branch may publish a new dataset version with explicitly
declared depth features; it must not mutate this one in place.

## Phased Route

| Phase | Inputs | Outputs | Acceptance gate | Rollback |
|---|---|---|---|---|
| 0. Task definition | This document, replay evidence, scene photos | Task spec, success/failure taxonomy, fixed scene ID | Team agrees on task string, start/end states and lift criterion | Return to the supervised replay only; do not collect data |
| 1. Hardware and calibration check | Jetson container smoke result, read-only port/camera checks, black-arm calibration cache | Dated preflight record and scene baseline record | No other hardware owner; camera stream and six joint observations are time-stable; all safety controls present | Stop at no-motion checks; keep `motion_locked` eye-to-hand fit out of execution |
| 2. Teleoperation recording | Approved recorder bridge reusing `arm_keyboard.py --terminal`, Gemini stream, dataset schema | LeRobotDataset pilot episodes and session ledger | Pilot episodes can be finalized, reopened, and replayed as data; no missing required feature or timestamp regression | Quarantine/delete only the new pilot dataset directory; return to manual controller |
| 3. Data QA | Finalized pilot/corpus dataset, ledger, scene photos | Immutable QA report, accepted episode manifest, holdout episode list | Schema uniform; episode-level split; images/state/actions aligned; only accepted demonstrations enter training | Exclude failed episodes by manifest, never patch frames in place |
| 4. ACT training | Accepted train manifest, fixed dataset revision, V100 allocation | Config, logs, checkpoints, validation metrics | Reproducible command/config; validation uses held-out episodes only; checkpoint and dataset revision recorded | Keep previous checkpoint; no deployment action |
| 5. Offline evaluation | Checkpoint, held-out episodes, action/state/video diagnostics | Offline evaluation report | Metrics and visual rollouts meet agreed threshold and reveal no unsafe saturation/drift pattern | Reject checkpoint; inspect data QA or train a new run |
| 6. Supervised real-robot test | Approved checkpoint, operator, emergency stop, empty path, hardware lock | Trial ledger, videos, success/failure counts | Each motion phase has an operator stop path; no collision; objective lift/hold criterion measured over predeclared trials | Cut 12V if needed, disconnect, return to manual/replay baseline; do not continue autonomous runs |

## ACT Technical Proposal

ACT is the first model because it is a small imitation-learning policy for
fine manipulation. It consumes the current joint state and one or more RGB
views and predicts an action chunk. The local LeRobot ACT config exposes
`chunk_size`, `n_action_steps`, and optional temporal ensembling; temporal
ensembling requires `n_action_steps=1`. First training starts from the
installed defaults and records every override in a checked-in training config.

Suggested progression after data QA, not an executable command for this round:

1. Train a small smoke run on V100 to validate loading, shapes and checkpoint
   creation.
2. Train the baseline with the accepted episode-level split. Start with the
   official ACT defaults; only adjust batch size for V100 memory.
3. Compare held-out action loss and visual episode diagnostics. Loss alone is
   not a release gate.
4. Run `lerobot-rollout` only after explicit approval for a supervised
   physical evaluation. The rollout must use the same camera feature names,
   FPS, robot calibration, and task contract as recording.

The official ACT guide describes ACT as a lightweight fine-manipulation
baseline and documents `lerobot-train` and `lerobot-rollout`. The
LeRobotDataset guide defines the common metadata, Parquet/video storage, and
finalization requirements. Sources:

- https://huggingface.co/docs/lerobot/main/act
- https://huggingface.co/docs/lerobot/lerobot-dataset-v3
- https://huggingface.co/docs/lerobot/main/inference

## Known Gaps Before Phase 2

1. The black-arm terminal controller must be connected to a dataset recorder
   through a small adapter. Reuse its terminal key mapping, calibration and P
   control; do not create a competing controller.
2. The Gemini RGB stream needs a LeRobot-compatible camera configuration or a
   narrowly scoped adapter. Confirm actual feature names, image shape, FPS and
   clock behavior in a no-motion integration check.
3. The data collector must explicitly call dataset finalization and verify the
   resulting dataset can be reopened before any data is trusted.
4. The scene needs a versioned physical baseline: photos, mount positions,
   lighting, jar orientation, start-cell grid and safe reset pose.
5. A team owner must approve objective evaluation thresholds before collecting
   the main corpus, so success labels are not chosen after training.

## Confirmation Gates

The following operations require explicit user confirmation in a later round:

- any arm movement, manual teleoperation or camera/serial access that owns
  hardware;
- new calibration or modification of existing calibration files;
- installation of large dependencies or rebuilding Jetson images;
- real data capture, V100 training, checkpoint upload, or remote deployment;
- any physical policy rollout.

This first round only creates this design and the accompanying collection
checklist.
