#!/bin/bash -l
# Read-only ACT evaluation on the four held-out fixed-scene episodes.
# This job never changes the dataset or checkpoint.
# The dataset copy and all outputs stay on Roihu; this script is safe to commit.
#SBATCH --job-name=xlerobot-act-eval-v2
#SBATCH --account=project_2016517
# gpumedium currently has a per-user submit limit of zero for this account.
# gpularge provides the same GH200 GPU class and accepts this one-GPU job.
#SBATCH --partition=gpularge
#SBATCH --time=00:15:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=/scratch/project_2016517/panh/summer-robotics-act/logs/%x_%j.out

export CSC_ENV_INIT_NON_INTERACTIVE=yes
source /etc/profile.d/zz-csc-env.sh
set -euo pipefail

ROOT=/scratch/project_2016517/panh/summer-robotics-act
DATASET="$ROOT/data/fixed_pick_place_v2_28ep"
CHECKPOINT="$ROOT/outputs/act_fixed_pick_place_v2_28ep_616995/checkpoints/006000/pretrained_model"
RESULT="$ROOT/artifacts/act_holdout_v2_28ep_${SLURM_JOB_ID}.json"
module purge
module load python-pytorch/2.10
source "$ROOT/.venv/bin/activate"
export HF_HOME="$ROOT/.cache/huggingface"
export TORCH_HOME="$ROOT/.cache/torch"
export PYTHONUNBUFFERED=1

echo "dataset=$DATASET"
echo "checkpoint=$CHECKPOINT"
echo "result=$RESULT"
python "$ROOT/artifacts/act_checkpoint_dry_run_v2.py" \
  --checkpoint "$CHECKPOINT" \
  --dataset-root "$DATASET" \
  --repo-id forestbridge/fixed-pick-place-v1 \
  --frame-indices 17222,17449,17676,17677,17939,18200,18201,18458,18714,18715,19012,19308 \
  --device cuda > "$RESULT"
cat "$RESULT"
