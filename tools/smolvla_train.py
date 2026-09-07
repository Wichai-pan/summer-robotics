"""Validated offline SmolVLA launcher; no hardware or automatic Hub upload."""
import argparse
import json
from pathlib import Path
import subprocess


def build_command(args):
    info = json.loads((args.dataset_root / "meta/info.json").read_text())
    features = info["features"]
    episodes = json.loads(args.episodes)
    if not isinstance(episodes, list) or not episodes or any(type(i) is not int for i in episodes):
        raise ValueError("Provide an explicit nonempty training episode list; keep holdout separate")
    if len(set(episodes)) != len(episodes) or any(i < 0 or i >= info["total_episodes"] for i in episodes):
        raise ValueError("Duplicate or out-of-range training episodes")
    for name in ("observation.state", "action"):
        shape = features[name]["shape"]
        if len(shape) != 1 or not 0 < shape[0] <= 32:
            raise ValueError(f"Unsupported {name} shape: {shape}")
    if "task_index" not in features:
        raise ValueError("Dataset must include task_index and meaningful task descriptions")
    rename = json.loads(args.rename_map)
    if not isinstance(rename, dict) or any(not isinstance(v, str) for v in rename.values()):
        raise ValueError("rename-map must be a JSON string mapping")
    if any(k not in features for k in rename):
        raise ValueError("rename-map references missing dataset features")
    target_keys = [rename.get(k, k) for k in features]
    if len(set(target_keys)) != len(target_keys):
        raise ValueError("rename-map creates duplicate features")
    cameras = [k for k, v in features.items() if v["dtype"] in ("video", "image")]
    if not cameras:
        raise ValueError("Dataset has no camera features")
    if args.steps <= 0 or args.batch_size <= 0:
        raise ValueError("steps and batch-size must be positive")
    save_freq = args.steps if args.save_freq is None else args.save_freq
    if save_freq <= 0 or save_freq > args.steps:
        raise ValueError("save-freq must be positive and not exceed steps")
    if args.output_dir.exists():
        raise ValueError("Output exists; choose a new run (no implicit overwrite/resume)")
    return [
        "lerobot-train", f"--policy.path={args.checkpoint}",
        f"--dataset.repo_id={args.repo_id}", f"--dataset.root={args.dataset_root}",
        f"--dataset.episodes={json.dumps(episodes)}", "--dataset.video_backend=pyav",
        f"--rename_map={json.dumps(rename)}", "--policy.device=cuda",
        "--policy.push_to_hub=false", "--wandb.enable=false", "--env_eval_freq=0",
        f"--steps={args.steps}", f"--batch_size={args.batch_size}", "--num_workers=4",
        "--seed=42", "--log_freq=10", f"--save_freq={save_freq}",
        f"--output_dir={args.output_dir}", "--job_name=forestbridge_smolvla",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--episodes", required=True, help='Training indices, e.g. "[0,1,2]"')
    parser.add_argument("--rename-map", default="{}", help="Map recorded camera keys to pretrained input keys")
    parser.add_argument("--checkpoint", default="lerobot/smolvla_base")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--save-freq", type=int, default=None,
                        help="Checkpoint interval; defaults to steps, i.e. a single end-of-run save")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Otherwise only validate and print argv")
    args = parser.parse_args()
    command = build_command(args)
    print(json.dumps({"argv": command, "execute": args.execute}, indent=2), flush=True)
    if args.execute:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; submit a GPU job")
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
