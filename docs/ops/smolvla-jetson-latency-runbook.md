# SmolVLA Jetson latency benchmark — runbook

Measures whether the trained SmolVLA checkpoint can sustain its control budget on
the Orin Nano. **Opens no USB device and issues no motor command; the robot does
not move.** It does take the shared hardware lock and contend for the GPU, so run
it only when no teammate is using the robot.

Background and the specs-only assessment: `docs/experiments/smolvla-longrun-20260907.md`.

## What is already prepared

- Benchmark script is on the Jetson at
  `/home/jetsonl7/robot-data/tmp/smolvla-latency-20260907/smolvla_jetson_latency.py`,
  visible inside the container as `/data/tmp/smolvla-latency-20260907/`.
  It sits outside `summer-robotics-deploy` on purpose: that clone is at `665eb4c`
  with local teammate modifications, and must not be switched or dirtied.
- Dataset `fixed_pick_place_v1` on the Jetson was verified identical to the Roihu
  copy: LeRobot v3.0, 28 episodes, 19,309 frames, 20 fps, same camera keys and
  action names. Episode 24 is held out from training.
- `external/lerobot` in the deploy clone is at the pinned `22bd7a2` and contains
  `src/lerobot/policies/smolvla/`, so the policy is importable.
- Image `forestbridge-xlerobot:jp62` is present. Disk has 48 GiB free.

- Checkpoint transferred to
  `/home/jetsonl7/robot-data/models/smolvla_fixed_pick_place_1097975_020000`
  (`/data/models/...` in the container), 869 MiB, `model.safetensors` verified by
  SHA256 `cfafd84c19e723b0e70c055a44273a8e09088a12e185b15d59ab84cad50cad18`
  against the Roihu source. Disk has 47 GiB free.

**Everything is staged. Only Steps 3–5 remain, and they need a free robot.**
Steps 1 and 2 below are kept for reproducing the transfer on another machine.

## Step 1 — refresh the Roihu certificate (interactive, about 30 s)

Certificates last 24 hours. Run on the Mac:

```bash
python3 ~/.local/certificate-helper-tool/csc_cert.py -u panh ~/.ssh/id_ed25519.pub
```

Authenticate, enter the six-digit code, unlock the SSH key. Verify:

```bash
bash ~/.codex/skills/roihu-cluster/scripts/check-certificate.sh
```

## Step 2 — copy the checkpoint to the Jetson (about 865 MiB)

```bash
SRC=/scratch/project_2016517/panh/summer-robotics-smolvla/outputs/1097975/train/checkpoints/020000/pretrained_model
DST=/home/jetsonl7/robot-data/models/smolvla_fixed_pick_place_1097975_020000
ssh roihu "tar cf - -C $SRC ." | ssh -o ServerAliveInterval=30 jetsonl7 "mkdir -p $DST && tar xf - -C $DST"
A=$(ssh roihu "sha256sum $SRC/model.safetensors" | cut -d' ' -f1)
B=$(ssh jetsonl7 "sha256sum $DST/model.safetensors" | cut -d' ' -f1)
if [ -n "$A" ] && [ "$A" = "$B" ]; then echo "OK $A"; else echo "MISMATCH: roihu='$A' jetson='$B'"; fi
```

The `-n "$A"` guard matters: comparing two empty strings otherwise reports a
false match when the source read fails, which is exactly what happened on the
first attempt after the certificate expired.

## Step 3 — confirm nobody is using the robot

```bash
ssh jetsonl7 'who; docker ps --format "{{.Names}} {{.Status}}"'
```

An empty `docker ps` means no ForestBridge container is running. If one is
listed, stop here; the benchmark would contend for the 8 GiB shared memory. The
hardware lock also fails closed with exit 3 if a container is already up.

## Step 4 — record the power mode

The 7W/15W/25W modes have substantially different clocks, so a number without
the mode is not interpretable. This needs root:

```bash
ssh jetsonl7 'sudo nvpmodel -q'
```

If sudo is unavailable, note that the mode is unknown when reporting the result.

## Step 5 — run the benchmark

```bash
ssh jetsonl7 'cd /home/jetsonl7/summer-robotics-deploy && ./scripts/jetson_robot_exec.sh -- \
  python3 /data/tmp/smolvla-latency-20260907/smolvla_jetson_latency.py \
    --checkpoint /data/models/smolvla_fixed_pick_place_1097975_020000 \
    --dataset-root /data/act/fixed_pick_place_v1 \
    --repo-id forestbridge/fixed-pick-place-v1 \
    --episode 24 --iterations 10 \
    --output /data/tmp/smolvla-latency-20260907/latency.json'
```

No device flag is passed, so no USB device is mapped into the container.

## How to read the result

The budget is `n_action_steps / fps` = 50 / 20 = **2.5 s**. One chunk must be
produced before the previous chunk finishes executing.

| Field | Meaning |
|---|---|
| `steady_median_s` | Typical chunk inference time, warmup call excluded |
| `steady_max_s` | Worst observed chunk |
| `budget_s` | 2.5 |
| `headroom_ratio` | `budget_s / steady_median_s`; above 1 means it keeps up |
| `sustains_budget` | True only when **every** steady call is under budget |
| `peak_allocated_gib` | Expect roughly 0.93 based on the GH200 measurement |

Interpretation:

- `headroom_ratio` comfortably above 2 — deployable at this chunk size.
- Between 1 and 2 — works, but with no margin for thermal throttling or
  concurrent Nav2 load. Prefer async inference before trusting it.
- Below 1 — cannot sustain 20 Hz as configured. Go to the fallbacks.

## Fallbacks if over budget, in cost order

1. Fewer denoising steps. The action expert runs `num_steps: 10` serial passes;
   this is an inference-time knob needing no retraining:

   ```bash
   # same command as Step 5, plus:
   --num-steps 5 --output /data/tmp/smolvla-latency-20260907/latency-steps5.json
   ```

   Compare accuracy afterwards by rerunning the Roihu holdout evaluation with the
   same override before accepting the tradeoff.
2. Async inference, starting the next chunk while the current one still executes,
   which effectively widens the budget beyond 2.5 s.
3. Reduce the 512×512 input padding.
4. TensorRT or int8. Best result, largest effort; leave until last.

## Do not do next without more work

Physical execution still needs an action clamping layer: the reload check decoded
`gripper.pos = -2.73`, a negative gripper position with no physical meaning. The
old data's `wrist_roll` is also a **velocity** command in deg/s, not an angle, and
an executor that treats it as a position will drive the wrist wrongly. Remote
physical motion remains prohibited without an on-site operator.
