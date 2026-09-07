# SmolVLA engineering validation — 2026-09-07

## Scope

User-authorized GPU smoke and short training on existing ACT demonstrations.
No robot connection, motor commands, Jetson deployment, data overwrite, or formal
new-task training. ACT environment, dataset and checkpoints remain intact.

The teammate-reported carrying decision is now **arm-held transport**, because
the basket trial was not feasible. The old dataset is a local pick/place task;
this run does not validate separate pickup, sustained hold, navigation with a
payload, or placement at another location.

## Environment and provenance

- Roihu root: `/scratch/project_2016517/panh/summer-robotics-smolvla`.
- Smoke/training project commit: `4cda458d07d2ace90fc3145103a8bc60107883f4`.
- Upstream LeRobot: `22bd7a2f489b367d8df42de803b1e8c4ca63a3f9`.
- Python 3.12; CSC torch `2.10.0+cu130`, torchvision `0.25.0+cu130`,
  Transformers 5.5.4 and PyAV 15.1.0; isolated system-site-packages venv.
- Policy snapshot: `c83c3163b8ca9b7e67c509fffd9121e66cb96205`.
- VLM snapshot: `7b375e1b73b11138ff12fe22c8f2822d8fe03467`.
- Jobs use a single GH200 on `gpularge`, offline cached models, no Hub upload.
- Per-job `outputs/<job-id>/` contains project revision, package freeze and
  model-snapshot manifest. Logs: `logs/forestbridge-smolvla_<job-id>.out`.

## Completed checks

| Check | Job | Result |
|---|---|---|
| Synthetic CUDA forward/backward, finite gradients, optimizer update, action inference | 1094450 | PASS, exit 0, 4m17s allocation |
| Old-data 100-step training and checkpoint save | 1094687 | PASS, exit 0, 5m09s allocation |
| Saved checkpoint reload and held-out observations | 1094988 | PASS, exit 0, 4m37s allocation |

Synthetic report: `outputs/1094450/smoke.json`; loss 0.3025206, action shape
`[1, 6]`, peak allocated GPU memory 1.7315 GiB. Reported GPU name is
`NVIDIA GH200 120GB`. Model test section took 5.87 s, excluding module/process
startup. This is not a Jetson speed or memory benchmark.

The training loop ran from 14:33:50 to 14:34:18 (cluster log time), with saved
weights confirmed at 14:34:19. Most allocation time preceded the loop. CSC ARGOS
connection/preload warnings appeared in both successful jobs; they did not
prevent completion. Do not confuse startup overhead with model throughput.

Logged training loss at steps 10/30/40/70/100 was
`0.631 / 0.445 / 2.037 / 0.290 / 0.291`: finite, not monotonically decreasing.
Steady logged update time was about 0.13–0.14 s/step, batch size 4; logged
`mem_gb` was about 2.16 (not an independently measured overall peak).
The model had 450,046,176 total and 99,880,992 learnable parameters with
`train_expert_only=true`. The short-run scheduler automatically scaled warmup
from 1000 to 3 and decay from 30000 to 100 steps.

## Old dataset and action contract

Dataset (read in place):
`/scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep`.
28 episodes, 19,309 frames total, LeRobot v3.0, 20 Hz. Training selected
episodes **0–23**, 17,222 frames; **24–27 did not participate in gradient training**.
Only 100 optimizer steps / 400 sampled items were used, not a full training run.

| Recorded camera | SmolVLA input |
|---|---|
| `observation.images.gemini_rgb` | `observation.images.camera1` |
| `observation.images.white_wrist_rgb` | `observation.images.camera2` |

Videos are 640×480 RGB, AV1, decoded through PyAV. No fabricated third-camera
frames are added. State and action each have six dimensions. **Wrist roll state
is `wrist_roll.pos`, but its action is `wrist_roll.vel_deg_s`**; other action
components are recorded joint/gripper position commands. Preserve this mixed
position/velocity contract during deployment; dimension equality is insufficient.

Normalization uses existing dataset metadata through LeRobot. Those statistics
can include the full dataset, so this holdout is an engineering check, **not a
strict leakage-free generalization benchmark**. A formal new-data experiment
must compute normalization from its training split and evaluate separately.

## Checkpoint reload and held-out inference

Job `1094988` reported `status: PASS`, exit 0, in a 4m37s allocation. Report:
`outputs/1094988/checkpoint-check.json`. The saved 100-step checkpoint reloaded
with its stored preprocessor/postprocessor configuration, and three held-out
observations from episode **24** decoded to finite six-dimensional actions with
both `camera1` and `camera2` present. The policy was reset between samples.
Peak allocated GPU memory was 0.9269 GiB on `NVIDIA GH200 120GB`. Per-sample
decode time was 0.758 s, 0.214 s and 0.209 s; the first includes warmup and
**none of these are Jetson latency figures**.

### Decoded actions versus recorded corpus range

Recorded action bounds come from dataset `meta/stats.json` over all 28 episodes:

| Dim | Name | Corpus min | Corpus max |
|---|---|---|---|
| 0 | `shoulder_pan.pos` | -36.396 | 3.868 |
| 1 | `shoulder_lift.pos` | -28.000 | 2.857 |
| 2 | `elbow_flex.pos` | -43.385 | 97.099 |
| 3 | `wrist_flex.pos` | -100.791 | -59.385 |
| 4 | `wrist_roll.vel_deg_s` | -7.998 | 7.910 |
| 5 | `gripper.pos` | 0.000 | 66.719 |

Two of eighteen decoded components fall outside that range, both in the third
sample (`dataset_index` 454):

- `wrist_flex.pos` = -102.383, i.e. 1.592° below the recorded minimum.
- `gripper.pos` = -2.730, i.e. 2.730 units below the recorded minimum of 0. A
  negative gripper position command has no physical meaning.

The other sixteen components lie inside the recorded range, and all
`wrist_roll.vel_deg_s` values were small (-0.127, 0.041, 0.046), consistent with
a velocity command rather than an angle.

This **reproduces the existing ACT-era open issue** in which predictions slightly
exceed the pilot corpus min/max. It is expected from a 100-step run and is not
itself a defect of SmolVLA, but it confirms that any executor must clamp to
trusted per-joint bounds and reject non-physical values before actuation. Do not
feed decoded actions straight to the arm.

## Reproduction

From the Roihu project clone:

```bash
sbatch jobs/roihu_smolvla.sh smoke

sbatch --time=00:30:00 jobs/roihu_smolvla.sh train \
  --dataset-root /scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep \
  --repo-id forestbridge/fixed-pick-place-v1 \
  --episodes '[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23]' \
  --rename-map '{"observation.images.gemini_rgb":"observation.images.camera1","observation.images.white_wrist_rgb":"observation.images.camera2"}' \
  --steps 100 --batch-size 4 --execute
```

Saved checkpoint:
`/scratch/project_2016517/panh/summer-robotics-smolvla/outputs/1094687/train/checkpoints/000100/pretrained_model`.
Contains ~865 MiB weights, model/train configs, tokenizer, pre/postprocessor JSON
and normalization safetensors. Training-state files are stored alongside it.

```bash
sbatch jobs/roihu_smolvla.sh check \
  --checkpoint /scratch/project_2016517/panh/summer-robotics-smolvla/outputs/1094687/train/checkpoints/000100/pretrained_model \
  --dataset-root /scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep \
  --repo-id forestbridge/fixed-pick-place-v1 --episode 24
```

This check uses saved normalization and camera mapping, resets the policy between
three sampled observations, and checks finite six-dimensional decoded actions.
It refuses an episode included in the saved training selection and refuses
overwriting an existing report. It never executes those actions.

## Closeout and remaining gates

All three planned engineering checks now pass: synthetic GPU (`1094450`),
100-step old-data training with checkpoint save (`1094687`) and checkpoint reload
with held-out inference (`1094988`). The three local guard tests in
`tests/test_smolvla_setup.py` also pass under Python 3.12
(`PYTHONPATH=. python3.12 tests/test_smolvla_setup.py`); the machine default
`python3` is pyenv 3.8.18 and cannot import `tomllib`. This closes the
training-pipeline availability question only. New dataset schema/quality validation,
meaningful full training, Jetson latency testing and supervised physical skill
validation remain necessary before deployment. Successful training is not
successful medicine/water delivery.

During this work GitHub gained teammate commits `046834c` and `8fefd78`
(living-room map and continuous home navigation baseline). They were preserved
and merged without conflicts; no teammate hardware code was rewritten.
