#!/usr/bin/env bash
# Lightweight setup only. GPU work belongs in jobs/roihu_smolvla.sh.
set -eo pipefail
export CSC_ENV_INIT_NON_INTERACTIVE=yes
source /etc/profile.d/zz-csc-env.sh
module purge
module load python-pytorch/2.10
export SMOL_ROOT=${SMOL_ROOT:-/scratch/project_2016517/panh/summer-robotics-smolvla}
revision=22bd7a2f489b367d8df42de803b1e8c4ca63a3f9
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ "$SMOL_ROOT" = /*summer-robotics-smolvla ]] || { echo 'Use a separate absolute summer-robotics-smolvla root'; exit 2; }
mkdir -p "$SMOL_ROOT"/{code,logs,outputs,data,manifests,.cache}
exec 9>"$SMOL_ROOT/.setup.lock"
flock -n 9 || { echo 'Another setup is active'; exit 2; }
if [[ ! -d "$SMOL_ROOT/code/lerobot/.git" ]]; then
  git clone https://github.com/huggingface/lerobot.git "$SMOL_ROOT/code/lerobot"
  git -C "$SMOL_ROOT/code/lerobot" checkout --detach "$revision"
fi
[[ $(git -C "$SMOL_ROOT/code/lerobot" rev-parse HEAD) = "$revision" ]]
[[ -z $(git -C "$SMOL_ROOT/code/lerobot" status --porcelain) ]]
if [[ ! -d "$SMOL_ROOT/.venv" ]]; then
  python -m venv --system-site-packages "$SMOL_ROOT/.venv"
fi
source "$repo/scripts/roihu_smolvla_env.sh"
python "$repo/tools/smolvla_dependencies.py" "$SMOL_ROOT/code/lerobot/pyproject.toml" > "$SMOL_ROOT/manifests/requirements.txt"
python -c 'import torch, torchvision; print("torch=="+torch.__version__); print("torchvision=="+torchvision.__version__)' > "$SMOL_ROOT/manifests/cuda-constraints.txt"
python -m pip install --no-cache-dir -c "$SMOL_ROOT/manifests/cuda-constraints.txt" -r "$SMOL_ROOT/manifests/requirements.txt"
python -m pip install --no-deps --no-build-isolation -e "$SMOL_ROOT/code/lerobot"
python -m pip freeze > "$SMOL_ROOT/manifests/environment-freeze.txt"
git -C "$repo" rev-parse HEAD > "$SMOL_ROOT/manifests/project-commit.txt"
git -C "$SMOL_ROOT/code/lerobot" rev-parse HEAD > "$SMOL_ROOT/manifests/lerobot-commit.txt"
python -c 'from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy; from lerobot.scripts.lerobot_train import main; print("PASS SmolVLA and training imports; GPU execution NOT tested")'
