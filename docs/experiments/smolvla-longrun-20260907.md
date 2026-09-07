# SmolVLA 20k-step training and held-out MAE — 2026-09-07

## Scope

First real-step-count SmolVLA training run, on the **existing ACT demonstrations**.
No robot connection, motor command, Jetson deployment or data overwrite. The ACT
environment, dataset and checkpoints are unchanged. The source dataset is
expected to be replaced by a new task recording, so this run is a pipeline and
convergence baseline, not a keeper model.

Continues `smolvla-validation-20260907.md`, which covered the synthetic GPU
check, the 100-step plumbing run and the checkpoint reload check.

## Training run 1097975

`COMPLETED`, exit 0, elapsed **01:05:19**, single GH200 on `gpularge`.

| Setting | Value |
|---|---|
| Steps | 20,000 |
| Batch size | 32 |
| `save_freq` | 4,000 |
| Training episodes | 0–23 (24 episodes / 17,222 frames) |
| Held out | 24–27, no gradient participation |
| Equivalent epochs | about 37 |
| Seed | 42 |
| LR schedule | warmup auto-scaled 1000 → 666, cosine decay 30000 → 20000 |
| Trainable parameters | 99,880,992 of 450,046,176 (`train_expert_only`, `freeze_vision_encoder`) |

Steady throughput was 0.17 s/step and 179 samples/s, with logged `mem_gb` flat at
7.91 for the entire hour. Five checkpoints were written at 4,000-step intervals,
1.3 GiB each, plus a `last` link. Long-run stability is therefore demonstrated
over a full hour, unlike the earlier 28-second loop.

Logged trajectory:

| step | 100 | 5,000 | 9,000 | 13,000 | 17,000 | 20,000 |
|---|---|---|---|---|---|---|
| loss | 0.421 | 0.056 | 0.062 | 0.021 | 0.017 | 0.019 |
| grad norm | 3.073 | 1.048 | 0.838 | 0.482 | 0.380 | 0.373 |

Loss fell about one and a half orders of magnitude and flattened after roughly
17,000 steps while the gradient norm decreased monotonically from 6.321. This is
genuine convergence, in contrast to the 100-step run where only noise was
visible. **It is training loss on 24 episodes across 37 epochs and very likely
includes substantial overfitting; it is not a generalization measurement.**

## Held-out evaluation 1099226

`status: PASS`. Scored checkpoint `020000` against recorded actions on the
**same twelve global frame indices the ACT v2 holdout used**
(`17222, 17449, 17676, 17677, 17939, 18200, 18201, 18458, 18714, 18715, 19012, 19308`),
covering held-out episodes 24–27. The policy is reset before each frame and only
the first action of the chunk is scored. Report:
`outputs/1099226/holdout-eval.json`.

| Dimension | SmolVLA 20k (this run) | ACT v2 step-6,000 | Unit |
|---|---|---|---|
| `shoulder_pan.pos` | **0.329** | 1.39 | degrees |
| `shoulder_lift.pos` | **0.291** | 1.87 | degrees |
| `elbow_flex.pos` | **1.048** | 3.73 | degrees |
| `wrist_flex.pos` | **0.310** | 1.06 | degrees |
| `gripper.pos` | **1.315** | 4.59 | recorder units |
| `wrist_roll.vel_deg_s` | 0.0056 | not reported | deg/s |

SmolVLA is roughly three to four times lower error on every dimension the ACT
holdout reported. The scoring protocol was checked against
`tools/act_checkpoint_dry_run.py` and is identical: reset, `select_action`, then
per-name MAE over the same frames. `elbow_flex` is the worst dimension for both
models, which suggests the metric tracks the same difficulty rather than noise.

**This is not a controlled architecture comparison.** ACT v2 trained at batch 8
for 6,000 steps, i.e. 48,000 samples or about 2.8 epochs in 6m18s, while this run
used batch 32 for 20,000 steps, i.e. 640,000 samples or about 37 epochs in
65 minutes — **13 times the training samples**. SmolVLA also starts from the
pretrained `smolvla_base` policy and a pretrained SmolVLM2 backbone, whereas the
ACT transformer trains from scratch. The result therefore compares a pretrained
VLA at a large budget against a from-scratch policy at a small one; how much of
the gap is architecture cannot be separated from compute and pretraining without
a budget-matched ACT rerun.

The error distribution is also skewed at n=12: `elbow_flex` has median 0.601
against mean 1.048 and max 3.994, and `gripper.pos` has median 0.799 against mean
1.315 and max 6.488. Means are the right comparison because ACT reported means,
but one or two frames dominate them, and no confidence interval is available
because ACT's per-frame errors were not retained. More epochs against a holdout
that is not leakage-free may also account for part of the improvement. `wrist_roll` has no ACT counterpart at this protocol; the
0.004 deg/s figure in earlier notes came from the 11-frame ACT v1 deployment
gate and is **not** comparable.

Peak allocated GPU memory was 0.9269 GiB. Chunk inference took 0.756 s on the
first call and a 0.210 s median afterwards; each call produces a 50-action chunk,
i.e. 2.5 s of 20 Hz control per inference on a GH200.

## Limits on what this shows

- Single-step action error is **not task success**. ACT reached 3.73° elbow error
  and still produced inconsistent physical grasps, so a lower MAE does not
  license any claim about grasping, transport or placement.
- Normalization statistics come from saved training metadata that can span the
  full dataset, so episodes 24–27 are not a leakage-free holdout. This is an
  engineering comparison under a protocol matched to ACT, not a clean
  generalization benchmark.
- The dataset carries exactly **one** task string for all 28 episodes
  (`total_tasks: 1`): "Pick up the blue face-cream jar from the fixed point,
  place it at the fixed target, and return the white arm to its folded rest
  pose." Language conditioning therefore has no discriminative signal here, and
  this run says nothing about instruction following. A multi-instruction
  recording is required before any language claim.
- Jetson latency and memory are **unmeasured**. GH200 figures do not transfer to
  an Orin Nano 8GB, and 450M total parameters is a materially heavier deployment
  target than ACT.
- No clamping layer exists yet. The earlier reload check decoded a negative
  `gripper.pos`, so an executor must reject non-physical values before actuation.
- Checkpoint resume was not exercised; only interval saving was verified.

## Reproduction

```bash
sbatch --time=06:00:00 jobs/roihu_smolvla.sh train \
  --dataset-root /scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep \
  --repo-id forestbridge/fixed-pick-place-v1 \
  --episodes '[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23]' \
  --rename-map '{"observation.images.gemini_rgb":"observation.images.camera1","observation.images.white_wrist_rgb":"observation.images.camera2"}' \
  --steps 20000 --batch-size 32 --save-freq 4000 --execute

sbatch --time=00:20:00 jobs/roihu_smolvla.sh eval \
  --checkpoint <SMOL_ROOT>/outputs/1097975/train/checkpoints/020000/pretrained_model \
  --dataset-root /scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep \
  --repo-id forestbridge/fixed-pick-place-v1 \
  --frame-indices 17222,17449,17676,17677,17939,18200,18201,18458,18714,18715,19012,19308
```

Code for both jobs is on branch `smolvla-longrun` at `583470b`; `main` was not
modified. `/scratch` held about 55 GiB free after the run.
