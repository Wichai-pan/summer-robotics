#!/bin/bash -l
# Single-device smoke or training. Override partition/time with sbatch if needed.
# Create SMOL_ROOT/logs before submission. Records runtime git provenance.
# No robot, camera, serial, or motor access.
#SBATCH --job-name=forestbridge-smolvla
#SBATCH --account=project_2016517
#SBATCH --partition=gpularge
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:gh200:1
#SBATCH --mem=64G
#SBATCH --time=00:15:00
#SBATCH --output=/scratch/project_2016517/panh/summer-robotics-smolvla/logs/%x_%j.out
set -eo pipefail
repo=${SMOL_REPO:-/scratch/project_2016517/panh/summer-robotics-smolvla/code/summer-robotics}
source "$repo/scripts/roihu_smolvla_env.sh"
set -u
cd "$repo"
[[ -n "${SLURM_JOB_ID:-}" ]] || { echo 'Submit using sbatch, not on a login node'; exit 2; }
[[ -z $(git status --porcelain) ]] || { echo 'Commit changes before running'; exit 2; }
run_dir="$SMOL_ROOT/outputs/${SLURM_JOB_ID}"
mkdir "$run_dir"
git rev-parse HEAD > "$run_dir/project-commit.txt"
cp "$SMOL_ROOT/manifests/environment-freeze.txt" "$run_dir/environment-freeze.txt"
export SMOL_RUN_DIR="$run_dir"
mode=${1:-smoke}
shift || true
case "$mode" in
  smoke) python tools/smolvla_smoke.py --output "$run_dir/smoke.json" "$@" ;;
  train) python tools/smolvla_train.py --output-dir "$run_dir/train" "$@" ;;
  *) echo 'Usage: sbatch jobs/roihu_smolvla.sh smoke|train [arguments]'; exit 2 ;;
esac
