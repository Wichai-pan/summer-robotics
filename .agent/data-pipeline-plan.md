# Data Pipeline Plan

> Generated with `data-pipeline-manager`. Update when the dataset schema,
> scene contract, or split protocol changes.

## Project

- Objective: train the first fixed-scene ACT pick-and-place policy.
- Pipeline version: `v1`
- Last updated: 2026-08-10

## Dataset

| Field | Value |
|---|---|
| Name | `forestbridge/fixed-pick-place-v1` |
| Version / release | local pilot `v1`; no public release yet |
| Source | on-robot demonstrations recorded on XLeRobot |
| Raw checksum | TODO after the accepted corpus is frozen |
| License | internal team data; publication license TBD |
| Known issues | wrist-roll action uses velocity while the other five joints use position; the black leader must stay outside the policy-camera view |

## Preprocessing Pipeline

1. Capture Gemini RGB and white-wrist RGB at 640x480 RGB — seed: N/A — `tools/act_episode_recorder.py`.
2. Sample the latest fresh frames at the 20 FPS control cycle; reject stale/repeated streams — seed: N/A.
3. Validate white-arm start/end against one saved folded-pose reference — seed: N/A — `tools/save_white_folded_pose.py`.
4. Record white follower state and the exact command sent in the same control cycle — seed: N/A.
5. Save only operator-approved complete episodes; write failures to `session_ledger.jsonl` — seed: N/A.
6. Finalize and reopen every accepted LeRobotDataset episode before reporting success — seed: N/A.

- Normalization fit scope: train only during ACT training.
- Augmentation applied to: train only; none during recording.
- Visual representation: uint8 RGB, 640x480, no crop in dataset v1.

## Split Protocol

The first 3-10 episodes are pipeline pilots and are not the frozen experiment
split.  Once 50 accepted fixed-scene episodes exist, assign complete episodes
with seed `20260810`:

| Split | Target | % | Grouping | Purpose |
|---|---:|---:|---|---|
| train | 30 episodes | 60% | episode | optimization |
| val | 10 episodes | 20% | episode | checkpoint/hyperparameter selection |
| test | 10 episodes | 20% | episode | one final fixed-scene evaluation |

Split method: seeded random, group-aware by `episode_index`; never split frames
from one episode across subsets.

Forbidden use of test split:

- No hyperparameter tuning.
- No threshold or checkpoint selection.
- No method selection.
- One final evaluation only.

Processed split checksums: TODO after corpus freeze.

## Data Quality Findings

| Finding | Severity | Status | Action |
|---|---|---|---|
| Jetson image lacked LeRobot dataset dependencies | blocker | resolved in temporary image | promote tested Docker change, then rebuild formal image |
| White wrist physical USB path was ambiguous | blocker | resolved | verified `2.4.1 = white`, `2.4.3 = black` using the known white-camera edge blemish |
| Wrist-roll uses velocity control | risk | documented | keep `wrist_roll.vel_deg_s` action name and use a matching deployment adapter |
| Moving black leader may leak into Gemini view | risk | open | keep leader outside/crop from policy view before corpus capture |
| Failed demonstrations can corrupt imitation targets | risk | resolved by protocol | retain only in ledger, not the ACT dataset |

## Contamination Assessment

- Contamination level: clean by construction if episode-level split is used.
- Audit method: episode IDs and accepted manifest; duplicate-frame checks during capture.
- Mitigation: never split frames; freeze test episode IDs before model tuning.

## Reproducibility Record

- Processing scripts: `tools/act_episode_recorder.py`,
  `tools/black_leads_white_wrap_safe.py`, and `tools/act_dataset_smoke.py`.
- Pipeline environment: LeRobot commit
  `22bd7a2f489b367d8df42de803b1e8c4ca63a3f9` (0.6.2),
  `deploy/jetson/Dockerfile` plus
  `requirements-control.txt` and `requirements-dataset.txt`.
- Storage: Jetson `/home/jetsonl7/robot-data/act/fixed_pick_place_v1`.
- Excluded samples: every operator-rejected, interrupted, stale-camera,
  collision, drop, timeout, or recovery episode.

## Open Items

| ID | Item | Owner | Due |
|---|---|---|---|
| ACT-DATA-1 | Promote the smoke-tested dataset image changes into the formal Jetson deployment | team | before hardware recording |
| ACT-DATA-2 | Confirm which physical wrist camera belongs to white arm | complete: `2.4.1` | 2026-08-10 |
| ACT-DATA-3 | Record scene photos and fixed folded/pick/place poses | on-site operator | before pilot |
| ACT-DATA-4 | Record and inspect 3 pilot episodes | team | before corpus capture |
