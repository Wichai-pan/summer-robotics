#!/usr/bin/env bash
# Source after CSC's module initialization; never modifies the ACT environment.
export CSC_ENV_INIT_NON_INTERACTIVE=yes
source /etc/profile.d/zz-csc-env.sh
module purge
module load python-pytorch/2.10
export SMOL_ROOT=${SMOL_ROOT:-/scratch/project_2016517/panh/summer-robotics-smolvla}
export HF_HOME="$SMOL_ROOT/.cache/huggingface"
export TORCH_HOME="$SMOL_ROOT/.cache/torch"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-4}
export PYTHONNOUSERSITE=1
unset PYTHONPATH
source "$SMOL_ROOT/.venv/bin/activate"
