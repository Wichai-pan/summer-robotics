# SmolVLA training preparation — 2026-09-06

## Scope and status

Prepare an isolated Roihu training environment while preserving the working ACT
baseline and the teammates' unpublished Jetson changes. No new medicine/water
dataset exists yet. This is infrastructure preparation, not a demonstrated VLA
robot skill or Jetson deployment.

The pinned LeRobot source is `22bd7a2f489b367d8df42de803b1e8c4ca63a3f9`
(package version 0.6.2), the same upstream revision used by the Roihu ACT setup.
The SmolVLA environment is separate because its Transformers requirement differs
from the existing ACT environment. CSC `python-pytorch/2.10` supplies ARM CUDA
PyTorch; pip must not replace it. Dataset decoding uses PyAV, not torchcodec
0.11 (which requires newer PyTorch).

## Paths and entrypoints

- Working root: `/scratch/project_2016517/panh/summer-robotics-smolvla`.
- Project clone: `code/summer-robotics`; pinned upstream clone: `code/lerobot`.
- Environment: `.venv`; downloaded models: `.cache/huggingface`.
- Data: `data/<immutable-dataset-version>`; do not overwrite the old ACT data.
- Outputs: `outputs/<Slurm-job-id>`; scheduler logs: `logs/forestbridge-smolvla_<job-id>.out`.
- `manifests/` records resolved packages, CUDA constraints and source revisions.
- Bootstrap: `scripts/roihu_smolvla_bootstrap.sh`.
- Slurm entry: `jobs/roihu_smolvla.sh`; default is a 15-minute single-GH200 smoke.
- Synthetic test: `tools/smolvla_smoke.py`; data launcher: `tools/smolvla_train.py`.

## After data arrives

1. Keep an immutable LeRobot dataset with RGB videos, state, recorded actions,
   timestamps/episode boundaries and meaningful task descriptions. Confirm camera
   identity, joint order, units, control frequency and position/velocity semantics;
   the old wrist-roll velocity must not be interpreted as a position angle.
2. Inspect several episodes including video alignment. Split by whole episodes,
   not random neighboring frames. Select train indices explicitly; keep a held-out
   set. The lightweight launcher checks metadata only, not actual dataset quality.
3. Map actual camera keys to the pretrained model's input camera keys deliberately.
   Do not invent a dual-arm schema before the recording hardware is settled.
4. Run a 100-step training smoke, then inspect loss, checkpoint reload and held-out
   outputs before deciding full training duration. Default batch size is 4, not an
   asserted optimal GH200 throughput setting.

From the project clone on Roihu (replace example values):

```bash
sbatch jobs/roihu_smolvla.sh smoke

sbatch --time=00:30:00 jobs/roihu_smolvla.sh train \
  --dataset-root /scratch/project_2016517/panh/summer-robotics-smolvla/data/DATASET_VERSION \
  --repo-id TEAM/DATASET \
  --episodes '[0,1,2]' \
  --steps 100 --batch-size 4 --execute
```

Omit `--execute` to print/validate the training command only. The job supplies a
unique output directory; existing output directories are refused. No model or
dataset is automatically uploaded to the Hub. A checkpoint can be given as a
local pinned snapshot with `--checkpoint`; record its revision for comparisons.
The synthetic smoke uses pretrained feature shapes and does not validate the
future robot's camera/action adapter.

## Capacity and outstanding verification

The September 6 storage check reported scratch at 939G/1.0T and 817K/1.0M files.
Check `csc-workspaces` before data uploads or long training; scratch is not backed
up and has a 180-day cleanup policy. Do not delete other projects to make space.
Full training, new-task generalization and Jetson latency/memory remain untested.

Official reference: [SmolVLA tutorial](https://huggingface.co/docs/lerobot/main/smolvla).
This workflow starts from the pretrained policy rather than training a VLA from scratch.
