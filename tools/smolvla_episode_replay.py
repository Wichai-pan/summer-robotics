"""Replay a held-out episode through SmolVLA chunk by chunk. No motor or serial access.

Observations come from the recording, so the policy never sees the consequences of
its own actions. This measures whether the predicted action trajectory tracks the
demonstration, not whether the task would succeed on hardware.
"""
import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--episode", type=int, required=True, help="Held-out episode only")
    parser.add_argument("--calibration", type=Path, default=None,
                        help="Follower calibration JSON, to report commands beyond the mechanical stops")
    parser.add_argument("--num-steps", type=int, default=None,
                        help="Override action-expert denoising steps")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.checkpoint.is_dir() or args.output.exists():
        raise ValueError("Checkpoint must exist and report must not already exist")
    train_config = json.loads((args.checkpoint / "train_config.json").read_text())
    train_episodes = train_config["dataset"].get("episodes")
    info = json.loads((args.dataset_root / "meta/info.json").read_text())
    if (not train_episodes or args.episode in train_episodes
            or not 0 <= args.episode < info["total_episodes"]):
        raise ValueError("Explicit held-out episode required")
    names = info["features"]["action"]["names"]
    stats = json.loads((args.dataset_root / "meta/stats.json").read_text())["action"]
    gripper = names.index("gripper.pos")
    calibrated = None
    if args.calibration:
        cal = json.loads(args.calibration.read_text()).get("gripper", {})
        if "range_min" in cal and "range_max" in cal:
            calibrated = (cal["range_min"], cal["range_max"])

    import torch
    from torch.utils.data import default_collate
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; run inside the Jetson GPU container")
    torch.manual_seed(42)
    policy = SmolVLAPolicy.from_pretrained(str(args.checkpoint)).to("cuda").eval()
    policy.config.device = "cuda"
    if args.num_steps is not None:
        policy.config.num_steps = args.num_steps
    pre, post = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(args.checkpoint),
        preprocessor_overrides={"device_processor": {"device": "cuda"}},
    )
    dataset = LeRobotDataset(
        args.repo_id, root=args.dataset_root, episodes=[args.episode], video_backend="pyav"
    )
    chunk = policy.config.n_action_steps
    recorded, predicted = [], []
    for start in range(0, len(dataset), chunk):
        sample = dataset[start]
        batch = pre(default_collate([{k: v for k, v in sample.items() if k != "action"}]))
        # Re-observe once per chunk and drain the queue, exactly as deployment does.
        policy.reset()
        with torch.inference_mode():
            for offset in range(min(chunk, len(dataset) - start)):
                action = post(policy.select_action(batch)).reshape(-1).cpu()
                if not torch.isfinite(action).all():
                    raise ValueError(f"Non-finite action at frame {start + offset}")
                predicted.append(action.tolist())
                recorded.append(dataset[start + offset]["action"].reshape(-1).tolist())

    mae = {n: statistics.mean(abs(p[i] - r[i]) for p, r in zip(predicted, recorded))
           for i, n in enumerate(names)}
    below = [i for i, p in enumerate(predicted) if p[gripper] < stats["min"][gripper]]
    above = [i for i, p in enumerate(predicted) if p[gripper] > stats["max"][gripper]]
    violations = {
        "corpus_min": stats["min"][gripper], "corpus_max": stats["max"][gripper],
        "frames_below_corpus_min": len(below), "frames_above_corpus_max": len(above),
        "worst_below": min((predicted[i][gripper] for i in below), default=None),
        "worst_above": max((predicted[i][gripper] for i in above), default=None),
    }
    if calibrated:
        span = calibrated[1] - calibrated[0]
        raw = [calibrated[0] + p[gripper] / 100.0 * span for p in predicted]
        violations["calibrated_raw_range"] = list(calibrated)
        violations["frames_beyond_mechanical_stop"] = sum(
            1 for r in raw if r < calibrated[0] or r > calibrated[1])
        violations["worst_raw_command"] = min(raw) if min(raw) < calibrated[0] else max(raw)

    step = max(1, len(recorded) // 24)
    trace = [{"frame": i, "recorded": round(recorded[i][gripper], 2),
              "predicted": round(predicted[i][gripper], 2)}
             for i in range(0, len(recorded), step)]
    report = {
        "hardware_tested": False,
        "measurement_scope": "open-loop trajectory tracking against a recording; not task success",
        "openloop_note": "Observations come from the recording, so the policy never sees the "
                         "consequences of its own actions. Compounding error is not measured",
        "checkpoint": str(args.checkpoint), "episode": args.episode,
        "frames": len(recorded), "chunk_size": chunk,
        "chunks": (len(recorded) + chunk - 1) // chunk,
        "num_steps": policy.config.num_steps,
        "mean_absolute_error": mae,
        "gripper_bounds": violations,
        "gripper_trace": trace,
    }
    args.output.write_text(json.dumps(
        {**report, "recorded": recorded, "predicted": predicted}, indent=2) + "\n")

    print(json.dumps({k: v for k, v in report.items() if k != "gripper_trace"}, indent=2))
    print("\ngripper: recorded | predicted")
    for t in trace:
        r, p = t["recorded"], t["predicted"]
        print(f"  {t['frame']:>4}  {r:>6.2f} {'#' * int(max(r, 0) / 3):<23}"
              f" | {p:>6.2f} {'#' * int(max(p, 0) / 3)}")


if __name__ == "__main__":
    main()
