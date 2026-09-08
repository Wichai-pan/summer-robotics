# SmolVLA session handoff — 2026-09-08

Written for whoever picks this up next, including an agent with no access to the
session that produced it. Everything below was verified, not inferred; where
something is unverified it says so.

Filed under `docs/experiments/` rather than taking a top-level number, because
`docs/20`–`docs/23` are already used by unpushed teammate work on the Jetson and
would collide.

## Where the work lives

Branch **`smolvla-longrun`**, pushed to `origin`, 11 commits ahead of `main`,
`+947 / -6` across 11 files. `main` was never modified.

```
55e3e41 docs: correct the description of the on-device clone
2ecd9fd feat(smolvla): measure Jetson chunk latency on device and record the result
b3e9af7 docs: record the completed checkpoint transfer to the Jetson
d94d54f docs: add the Jetson latency benchmark runbook
e38ee73 feat(smolvla): add Jetson chunk-latency benchmark and record the feasibility assessment
eecf3d7 docs: split the wrist_roll note out of the comparison caveat paragraph
668574f docs: qualify the SmolVLA-versus-ACT MAE gap
d701b50 docs: record SmolVLA 20k-step run and held-out MAE
583470b feat(smolvla): add held-out per-joint MAE evaluation
e0d2ee2 feat(smolvla): add --save-freq for resumable long training runs
ce18765 docs: close out SmolVLA engineering validation
```

**Open decision: whether to merge this into `main`.** It carries a `--save-freq`
fix and two new evaluation tools teammates would likely use.

## What was done

Started by finishing an interrupted validation: job `1094988` had already
completed but its result was never read.

| Job | What | Result |
|---|---|---|
| `1094450` | Synthetic CUDA forward/backward/inference | PASS, 4m17s |
| `1094687` | 100-step training on old ACT data | PASS, 5m09s |
| `1094988` | Checkpoint reload + held-out inference | **PASS**, 4m37s |
| `1097975` | **20,000-step training**, batch 32 | **COMPLETED, exit 0, 01:05:19** |
| `1099226` | Held-out per-joint MAE | **PASS** |

Then, on device, the Jetson chunk-latency benchmark.

### Training 1097975

20,000 steps at batch 32, `save_freq` 4,000, seed 42, episodes 0–23 (24 episodes
/ 17,222 frames, about 37 epochs), holdout 24–27. Warmup auto-scaled 1000 → 666,
cosine decay 30000 → 20000. `train_expert_only` with `freeze_vision_encoder`:
99,880,992 trainable of 450,046,176.

Loss 0.421 → 0.019, gradient norm 6.321 → 0.373 monotonically, flattening after
about 17,000 steps. Throughput 0.17 s/step and logged `mem_gb` flat at 7.91 for
the whole hour, so long-run stability holds.

Checkpoints `004000 008000 012000 016000 020000 last`, 1.3 GiB each, under
`/scratch/project_2016517/panh/summer-robotics-smolvla/outputs/1097975/train/checkpoints/`.

### Held-out MAE 1099226 versus ACT

Same twelve global frame indices the ACT v2 holdout used
(`17222,17449,17676,17677,17939,18200,18201,18458,18714,18715,19012,19308`),
episodes 24–27. Protocol verified identical against
`tools/act_checkpoint_dry_run.py`: reset, `select_action`, per-name MAE.

| Dimension | SmolVLA 20k | ACT v2 step-6,000 | Unit |
|---|---|---|---|
| `shoulder_pan.pos` | 0.329 | 1.39 | deg |
| `shoulder_lift.pos` | 0.291 | 1.87 | deg |
| `elbow_flex.pos` | 1.048 | 3.73 | deg |
| `wrist_flex.pos` | 0.310 | 1.06 | deg |
| `gripper.pos` | 1.315 | 4.59 | units |
| `wrist_roll.vel_deg_s` | 0.0056 | not reported | deg/s |

**Do not read this as an architecture verdict.** ACT trained at batch 8 for 6,000
steps — 48,000 samples, about 2.8 epochs — against 640,000 samples here, so
SmolVLA got **13 times the training samples** and additionally started from a
pretrained VLA policy and VLM backbone. It compares a pretrained VLA at a large
budget against a from-scratch policy at a small one. A budget-matched ACT rerun
(batch 32 × 20,000 steps, then the same eval) would separate architecture from
compute and costs well under an hour.

### Jetson latency, measured on device

25W power mode confirmed via `nvpmodel -q` (works without sudo), CPU at its
1344 MHz ceiling, about 49 °C, nothing else running.

| | Run 1 | Run 2 (preprocessing timed) |
|---|---|---|
| Policy inference median | 1.123 s | 1.220 s |
| Preprocessing median | not timed | 0.0066 s |
| End-to-end median | — | **1.226 s** |
| Headroom vs the 2.5 s budget | 2.23x | **2.04x** |
| Peak allocated | 0.9026 GiB | 0.9042 GiB |
| `sustains_budget` | true | true |

Budget is `n_action_steps / fps` = 50 / 20 = 2.5 s. **Verdict: the hardware runs
this checkpoint with about two times headroom.** Use the conservative 2.04x.

Reports: `/data/tmp/smolvla-latency-20260907/latency.json` and `latency-e2e.json`.

## New code

- `tools/smolvla_train.py` — added `--save-freq`. It was pinned to `--steps`, so a
  run only checkpointed at its final step and a multi-hour failure left nothing.
  Explicit `0` and values above `steps` are rejected.
- `tools/smolvla_holdout_eval.py` — per-joint MAE against recorded actions on
  explicit frame indices, ACT-matched protocol, refuses training-episode frames.
- `tools/smolvla_jetson_latency.py` — chunk latency and memory, resets each
  iteration so every call is a full inference rather than a queue pop, times
  preprocessing separately, samples clocks mid-loop, `--num-steps` override.
- `jobs/roihu_smolvla.sh` — new `eval` mode.
- `tests/test_smolvla_setup.py` — 5 tests, all passing.

Tests need Python 3.12; the machine default `python3` is pyenv 3.8.18 and cannot
import `tomllib`. There is no `pytest`. Run:
`PYTHONPATH=. python3.12 tests/test_smolvla_setup.py`

## Traps found the hard way

**The `jp62` image lacks every SmolVLA dependency.** `transformers`, `tokenizers`,
`num2words`, `docopt` and `accelerate` are all absent, and its
`regex==2024.11.6` is below the `regex>=2025.10.22` that `transformers` 5.5.4
enforces at import. Installed with `--no-deps` into
`/data/tmp/smolvla-latency-20260907/pydeps`, reached via `PYTHONPATH`.
`--no-deps` is required: a plain install pulls newer `numpy` and `safetensors`
that shadow what the NVIDIA torch build expects. To enumerate the constraints
without triggering the failing check, read
`transformers/dependency_versions_check.py` and `dependency_versions_table.py`
as text — importing the check module raises.

**`/home/jetsonl7/summer-robotics-deploy` is an active working tree, not a synced
deployment checkout.** As of 2026-09-08 it is on
`codex/pick-hold-place-segment-recorder`, 2 ahead of and 8 behind `origin/main`,
with 13 modified tracked files and 47 untracked entries including 23 new scripts
and tools. The commits are pushed to
`origin/codex/single-arm-pick-hold-place-segment-recorder`; **the working tree is
not pushed anywhere.** Never run `checkout`, `reset` or `pull` there. Its remote
is the `git@github-joanna:` alias, a different identity from the Mac's HTTPS
remote. This contradicts the older claim in `docs/ops/current-status.md` that the
clone tracks `origin/main`.

**`nvpmodel -q` works without sudo.** The `gpu_hz` field the benchmark records is
unreliable — it returned the same floor value under load and at rest, so the
probed devfreq node is not the graphics clock. Trust `nvpmodel`.

**Roihu certificates last 24 hours** and expiry surfaces as
`Permission denied (publickey)`. Refresh with
`python3 ~/.local/certificate-helper-tool/csc_cert.py -u panh ~/.ssh/id_ed25519.pub`.
When comparing checksums across hosts, guard against an empty read: two empty
strings compare equal and report a false match, which happened once here.

## Blocking gate before any physical run

**An action clamping layer does not exist.** The reload check decoded
`gripper.pos = -2.73`, a negative gripper position with no physical meaning, and
2 of 18 decoded components fell outside the recorded corpus range. Feeding
decoded actions straight to hardware is how the gripper gets damaged.

The old corpus's `wrist_roll` is a **velocity** command in `deg/s`, not an angle.
An executor treating it as a position will drive the wrist wrongly. Dimension
equality is not enough.

Remote physical motion remains prohibited without an on-site operator.

## What this does not show

- Single-step action error is **not task success**. ACT sat at 3.73° elbow error
  and still grasped inconsistently.
- Normalization statistics may span the full dataset, so episodes 24–27 are not a
  leakage-free holdout. This is an engineering comparison, not a generalization
  benchmark.
- The corpus carries exactly **one** task string for all 28 episodes
  (`total_tasks: 1`). Language conditioning has no discriminative signal, so
  nothing here says anything about instruction following. If the new recording
  also has a single instruction, SmolVLA's language pathway stays unused and ACT
  is the lighter choice; multiple distinct instructions are needed to exercise it.
- Camera capture cost, concurrent Nav2/RTAB-Map load, sustained warm-room
  thermals and checkpoint resume are all unmeasured.
- Training loss 0.019 over 37 epochs on 24 episodes very likely includes
  substantial overfitting.

## Suggested next steps

1. **Action clamping layer.** The only hard blocker before physical execution.
   Per-joint bounds from `meta/stats.json`, reject non-physical values, preserve
   the `wrist_roll` velocity semantics.
2. **Decide the instruction count for the new recording** before collecting it.
   This choice determines whether SmolVLA is even the right architecture.
3. Budget-matched ACT rerun, if the architecture comparison matters.
4. Merge `smolvla-longrun` into `main`, or say why not.
5. Ask whoever owns the Jetson working tree to push it. 23 new scripts and tools
   exist only on an SD card in a machine that gets USB-cycled and runs motors.
6. If SmolVLA becomes the deployment path, put its dependencies into
   `deploy/jetson/Dockerfile` in this repository and rebuild. Do not edit the
   on-device clone.

## Reference paths

- Roihu root: `/scratch/project_2016517/panh/summer-robotics-smolvla`
- Roihu dataset: `/scratch/project_2016517/panh/summer-robotics-act/data/fixed_pick_place_v2_28ep`
- Jetson checkpoint: `/home/jetsonl7/robot-data/models/smolvla_fixed_pick_place_1097975_020000`
  (869 MiB, `model.safetensors` SHA256 `cfafd84c19e723b0e70c055a44273a8e09088a12e185b15d59ab84cad50cad18`)
- Jetson dataset: `/home/jetsonl7/robot-data/act/fixed_pick_place_v1` (verified
  identical to the Roihu copy: v3.0, 28 episodes, 19,309 frames, 20 fps)
- Jetson benchmark and deps: `/home/jetsonl7/robot-data/tmp/smolvla-latency-20260907/`
- Detail: `docs/experiments/smolvla-longrun-20260907.md`,
  `docs/experiments/smolvla-validation-20260907.md`,
  `docs/ops/smolvla-jetson-latency-runbook.md`
