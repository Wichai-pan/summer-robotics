#!/bin/bash -l
# ACT comparison run: 24 training episodes from the 28-episode fixed-scene corpus.
# Episodes 24-27 remain untouched for post-training offline checks.
# The dataset copy and all outputs stay on Roihu; this script is safe to commit.
#SBATCH --job-name=xlerobot-act-v2-28ep
#SBATCH --account=project_2016517
# gpumedium currently has a per-user submit limit of zero for this account.
# gpularge provides the same GH200 GPU class and accepts this one-GPU job.
#SBATCH --partition=gpularge
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=/scratch/project_2016517/panh/summer-robotics-act/logs/%x_%j.out

export CSC_ENV_INIT_NON_INTERACTIVE=yes
source /etc/profile.d/zz-csc-env.sh
set -euo pipefail

ROOT=/scratch/project_2016517/panh/summer-robotics-act
DATASET="$ROOT/data/fixed_pick_place_v2_28ep"
OUTPUT="$ROOT/outputs/act_fixed_pick_place_v2_28ep_${SLURM_JOB_ID}"
TRAIN_EPISODES='[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23]'

module purge
module load python-pytorch/2.10
source "$ROOT/.venv/bin/activate"
export HF_HOME="$ROOT/.cache/huggingface"
export TORCH_HOME="$ROOT/.cache/torch"
export PYTHONUNBUFFERED=1

echo "dataset=$DATASET"
echo "train_episodes=$TRAIN_EPISODES"
echo "holdout_episodes=[24,25,26,27]"
echo "output=$OUTPUT"

lerobot-train \
  --dataset.repo_id=forestbridge/fixed-pick-place-v1 \
  --dataset.root="$DATASET" \
  --dataset.episodes="$TRAIN_EPISODES" \
  --dataset.video_backend=pyav \
  --dataset.return_uint8=true \
  --policy.type=act \
  --policy.device=cuda \
  --policy.use_amp=true \
  --policy.push_to_hub=false \
  --output_dir="$OUTPUT" \
  --job_name=xlerobot_act_fixed_pick_place_v2_28ep \
  --batch_size=8 \
  --num_workers=8 \
  --steps=6000 \
  --env_eval_freq=0 \
  --log_freq=100 \
  --save_freq=1000 \
  --wandb.enable=false

echo "TRAIN_OUTPUT=$OUTPUT"
