"""Per-joint MAE of a saved SmolVLA checkpoint on held-out frames, never hardware."""
import argparse
import json
from pathlib import Path
import time


def parse_frames(text, total_frames):
    frames = sorted({int(part) for part in text.split(",") if part.strip()})
    if not frames or any(not 0 <= i < total_frames for i in frames):
        raise ValueError("Provide explicit in-range frame indices")
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--frame-indices", required=True,
                        help="Global dataset frame indices, matching the ACT holdout protocol")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.checkpoint.is_dir() or args.output.exists():
        raise ValueError("Checkpoint must exist and report must not already exist")
    train_config = json.loads((args.checkpoint / "train_config.json").read_text())
    train_episodes = train_config["dataset"].get("episodes")
    if not train_episodes:
        raise ValueError("Checkpoint must record its training episode selection")
    info = json.loads((args.dataset_root / "meta/info.json").read_text())
    names = info["features"]["action"]["names"]
    frames = parse_frames(args.frame_indices, info["total_frames"])

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
    dataset = LeRobotDataset(args.repo_id, root=args.dataset_root, video_backend="pyav")
    samples = []
    for index in frames:
        sample = dataset[index]
        episode = int(sample["episode_index"])
        if episode in train_episodes:
            raise ValueError(f"Frame {index} belongs to training episode {episode}")
        target = sample["action"].reshape(-1)
        if target.shape[0] != len(names):
            raise ValueError("Recorded action does not match the declared action names")
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
            action = post(policy.select_action(batch))
        torch.cuda.synchronize()
        if action.shape != (1, len(names)) or not torch.isfinite(action).all():
            raise ValueError("Invalid decoded action")
        predicted = action.reshape(-1).cpu()
        samples.append({"dataset_index": index, "episode": episode, "task": sample["task"],
                        "cameras": cameras, "predicted": predicted.tolist(),
                        "recorded": target.tolist(),
                        "absolute_error": (predicted - target).abs().tolist(),
                        "inference_s": time.monotonic() - start})
    mae = {name: sum(s["absolute_error"][i] for s in samples) / len(samples)
           for i, name in enumerate(names)}
    report = {"status": "PASS", "hardware_tested": False,
              "validation_scope": "single-step action error on held-out frames; not grasp success",
              "normalization_note": "Saved training statistics may originate from full dataset metadata; not a strict generalization benchmark",
              "protocol_note": "Policy is reset before each frame and only the first action of the chunk is scored, matching the ACT holdout comparison",
              "unit_note": "Position dimensions are degrees, wrist_roll is deg/s, gripper is recorder units",
              "checkpoint": str(args.checkpoint), "dataset_root": str(args.dataset_root),
              "train_episodes": train_episodes,
              "heldout_episodes": sorted({s["episode"] for s in samples}),
              "frame_indices": frames, "action_names": names,
              "mean_absolute_error": mae,
              "gpu": torch.cuda.get_device_name(),
              "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
              "samples": samples}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
