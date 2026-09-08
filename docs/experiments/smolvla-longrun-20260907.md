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
that is not leakage-free may also account for part of the improvement.

`wrist_roll` has no ACT counterpart at this protocol; the 0.004 deg/s figure in
earlier notes came from the 11-frame ACT v1 deployment gate and is **not**
comparable.

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
- Jetson latency and memory were **measured on 2026-09-08 and pass**; see the
  section below. The remaining deployment gaps are the clamping layer, camera
  capture cost and concurrent ROS load, not raw feasibility.
- No clamping layer exists yet. The earlier reload check decoded a negative
  `gripper.pos`, so an executor must reject non-physical values before actuation.
- Checkpoint resume was not exercised; only interval saving was verified.

## Jetson measurement — 2026-09-08

Ran on the device in the `forestbridge-xlerobot:jp62` container with no device
flag, so no USB device was mapped and no motor command was issued. Power mode
confirmed as **25W**, the highest available, via `nvpmodel -q`. CPU sat at its
1344 MHz scaling ceiling under load at about 49 °C.

| | Run 1 | Run 2 (preprocessing included) |
|---|---|---|
| Policy inference median | 1.123 s | 1.220 s |
| Preprocessing median | not timed | **0.0066 s** |
| End-to-end median | — | **1.226 s** |
| Headroom against the 2.5 s budget | 2.23x | **2.04x** |
| Peak allocated memory | 0.9026 GiB | 0.9042 GiB |
| `sustains_budget` | true | true |

**Verdict: the hardware runs this checkpoint with roughly two times headroom.**
Take the more conservative 2.04x. The two runs differ by 8.6 percent, which is
run-to-run variation rather than a trend, and every steady call in both runs was
under budget.

Per-chunk preprocessing costs 6.6 ms, about 0.5 percent of the budget, so the
first run's omission of it did not distort the conclusion. Memory came in at
0.904 GiB against the 0.9269 GiB predicted from the GH200 measurement, so that
part of the specs-only estimate was accurate. **The latency estimate was too
pessimistic**: the predicted range was 1.7–5 s and the measurement is 1.23 s,
because scaling GH200 throughput by compute and bandwidth ratios understated how
Orin handles this small-batch serial workload.

Still excluded, and each eats into the 1.27 s of slack:

- **Camera capture.** A decoded dataset frame stands in for live capture.
- **Concurrent load.** Nothing else was running. The demo pipeline docks before
  running the policy, so the Nav2 and RTAB-Map peaks should not coincide, but
  that was not tested together.
- **Sustained thermals.** 49 °C in a cool room over ten iterations is not a
  warm-room endurance test.

The `gpu_hz` field in the reports is unreliable: it returned the same floor value
under load and at rest, so the probed devfreq node is not the graphics clock. The
power mode from `nvpmodel -q` is the trustworthy figure.

### Container dependency gap

The `jp62` image was built for ACT and lacks everything SmolVLA needs:
`transformers`, `tokenizers`, `num2words`, `docopt` and `accelerate` were all
absent, and the image's `regex==2024.11.6` is below the `regex>=2025.10.22` that
`transformers` 5.5.4 enforces at import. Present and sufficient were
`huggingface_hub==1.27.0`, `safetensors==0.5.3`, `numpy==1.26.4`, `filelock`,
`packaging`, `psutil`, `PyYAML`, `requests` and `tqdm`.

These were installed with `--no-deps` into `/data/tmp/smolvla-latency-20260907/pydeps`
at the versions that produced this checkpoint on Roihu, and reached through
`PYTHONPATH`. `--no-deps` matters: a plain install would have pulled newer
`numpy` and `safetensors` that shadow the ones the NVIDIA torch build expects.
This is a measurement workaround, removable with one `rm -rf`. If SmolVLA becomes
the deployment path, `deploy/jetson/Dockerfile` needs these dependencies properly
— that file currently carries uncommitted teammate modifications and must not be
overwritten.

## Jetson feasibility assessment — specs only, superseded by the measurement above

Requested on 2026-09-07 while teammates held the robot. Read-only inspection
over Tailscale; no benchmark was run and no device was opened.

**Memory passes with margin.** The Jetson has 7.4 GiB unified CPU/GPU memory with
5.2 GiB available at rest and 3.7 GiB of unused swap. Weights are 906,712,552
bytes, i.e. 865 MiB at two bytes per parameter, and the measured GH200 peak of
0.9269 GiB already includes them, so activations cost only about 85 MiB at batch
one. Nav2 and RTAB-Map are the real memory consumers, but the existing pipeline
docks first and runs the policy afterwards, so those peaks do not coincide.

**Latency is the open question and cannot be settled from specs.** The budget is
`n_action_steps / fps` = 50 / 20 = **2.5 s**: one chunk must be produced before
the previous chunk finishes executing.

ACT's measured 20 Hz rollouts are *not* a usable anchor for per-inference
latency, because ACT's `chunk_size` is 100, giving it a 5.0 s budget and only six
inferences across a 600-step rollout. The workload ratio is informative instead:

| | ACT | SmolVLA |
|---|---|---|
| Weights | 206 MB fp32, about 51.7M parameters | 906 MB bf16, 450M parameters |
| Vision | `resnet18` | SmolVLM2-500M, inputs padded to 512×512, two cameras |
| Forwards per inference | 1 | 1 VLM prefill plus **10 serial action-expert steps** (`num_steps: 10`) |
| Chunk / budget | 100 steps / 5.0 s | 50 steps / **2.5 s** |

Parameters differ by 8.7 times, but the serial ten-step expert loop makes the
compute gap larger. Scaling the 0.210 s GH200 median by the Orin Nano Super's
roughly 30–60× lower compute and 102 GB/s versus multi-TB/s bandwidth, while
allowing for GH200 being badly underutilised at batch one, gives an estimate of
**1.7–5 s per chunk against a 2.5 s budget**. The range straddles the
requirement, so the outcome is genuinely undetermined until measured.

The `nvpmodel` power mode could not be read without root. Confirm it before
trusting any measurement, since the 7W/15W/25W clocks differ substantially; the
GPU was idling at 306 MHz during inspection.

If measurement lands over budget, in cost order: reduce `num_steps` from 10 to
4–5 as an inference-time knob needing no retraining; overlap inference with chunk
execution asynchronously, which effectively widens the budget; reduce the 512×512
input padding; and only then consider TensorRT or int8.

`tools/smolvla_jetson_latency.py` performs this measurement. It opens no USB
device and issues no motor command, so it does not take the hardware lock, but it
does contend for the shared GPU and must run in an agreed window.

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
