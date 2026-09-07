"""Reload a saved SmolVLA checkpoint and infer on held-out data, never hardware."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.checkpoint.is_dir() or args.output.exists():
        raise ValueError("Checkpoint must exist and report must not already exist")
    train_config = json.loads((args.checkpoint / "train_config.json").read_text())
    train_episodes = train_config["dataset"].get("episodes")
    info = json.loads((args.dataset_root / "meta/info.json").read_text())
    if (train_episodes is None or args.episode in train_episodes
            or not 0 <= args.episode < info["total_episodes"]):
        raise ValueError("Explicit held-out episode required")

    import torch
    from torch.utils.data import default_collate
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; use a Slurm GPU allocation")
    torch.manual_seed(42)
    policy = SmolVLAPolicy.from_pretrained(str(args.checkpoint)).to("cuda").eval()
    policy.config.device = "cuda"
    # Load SAVED processors/statistics, not fresh statistics from the holdout.
    pre, post = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(args.checkpoint),
        preprocessor_overrides={"device_processor": {"device": "cuda"}},
    )
    dataset = LeRobotDataset(
        args.repo_id, root=args.dataset_root, episodes=[args.episode], video_backend="pyav"
    )
    results = []
    for index in sorted({0, len(dataset) // 2, len(dataset) - 1}):
        sample = dataset[index]
        batch = default_collate([sample])
        batch.pop("action", None)
        batch = pre(batch)
        cameras = sorted(k for k in policy.config.image_features if k in batch)
        if len(cameras) != 2:
            raise ValueError(f"Expected both recorded RGB cameras, got {cameras}")
        policy.reset()
        torch.cuda.synchronize()
        start = time.monotonic()
        with torch.inference_mode():
            normalized = policy.select_action(batch)
            action = post(normalized)
        torch.cuda.synchronize()
        if action.shape != (1, 6) or not torch.isfinite(action).all():
            raise ValueError("Invalid decoded action")
        results.append({"dataset_index": index, "episode": args.episode,
                        "task": sample["task"], "cameras": cameras,
                        "action": action.cpu().tolist(),
                        "inference_s": time.monotonic() - start})
    report = {"status": "PASS", "hardware_tested": False,
              "validation_scope": "checkpoint reload and finite held-out inference only; not grasp success",
              "normalization_note": "Saved training statistics may originate from full dataset metadata; not a strict generalization benchmark",
              "checkpoint": str(args.checkpoint), "dataset_root": str(args.dataset_root),
              "train_episodes": train_episodes, "heldout_episode": args.episode,
              "gpu": torch.cuda.get_device_name(),
              "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
              "samples": results}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
