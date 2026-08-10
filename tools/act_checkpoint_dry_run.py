#!/usr/bin/env python3
"""Load a trained ACT checkpoint and infer on recorded frames without hardware.

This program never opens a camera, serial port, or motor bus.  It is the first
deployment gate after training: checkpoint loading, saved normalization,
dataset decoding, CUDA inference, and action ordering must all work before a
live-camera or physical rollout is considered.
"""

from __future__ import annotations

import argparse
import json
import math
from contextlib import nullcontext
from pathlib import Path

import torch


OBSERVATION_KEYS = (
    "observation.state",
    "observation.images.gemini_rgb",
    "observation.images.white_wrist_rgb",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", default="forestbridge/fixed-pick-place-v1")
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


def scalar(value: object) -> int:
    if isinstance(value, torch.Tensor):
        return int(value.item())
    return int(value)


def bounds_status(
    values: list[float], minimum: list[float], maximum: list[float]
) -> list[bool]:
    if not (len(values) == len(minimum) == len(maximum)):
        raise ValueError("values and bounds must have the same length")
    return [lo <= value <= hi for value, lo, hi in zip(values, minimum, maximum)]


def main() -> int:
    args = parse_args()
    if not args.checkpoint.is_dir():
        raise SystemExit(f"checkpoint directory does not exist: {args.checkpoint}")
    if not args.dataset_root.is_dir():
        raise SystemExit(f"dataset directory does not exist: {args.dataset_root}")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but torch.cuda.is_available() is false")

    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import get_policy_class, make_pre_post_processors

    device = torch.device(args.device)
    dataset = LeRobotDataset(
        repo_id=args.repo_id,
        root=args.dataset_root,
        video_backend="pyav",
        download_videos=False,
    )
    if not 0 <= args.frame_index < dataset.num_frames:
        raise SystemExit(
            f"frame index {args.frame_index} outside [0, {dataset.num_frames - 1}]"
        )

    config = PreTrainedConfig.from_pretrained(args.checkpoint)
    config.device = str(device)
    policy_class = get_policy_class(config.type)
    policy = policy_class.from_pretrained(args.checkpoint, config=config).to(device)
    policy.eval()
    policy.reset()

    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=config,
        pretrained_path=str(args.checkpoint),
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )

    frame = dataset[args.frame_index]
    missing = [key for key in OBSERVATION_KEYS if key not in frame]
    if missing:
        raise RuntimeError(f"dataset frame is missing policy inputs: {missing}")
    observation = {key: frame[key].unsqueeze(0) for key in OBSERVATION_KEYS}

    autocast = (
        torch.autocast(device_type="cuda")
        if device.type == "cuda" and config.use_amp
        else nullcontext()
    )
    with torch.inference_mode(), autocast:
        processed_observation = preprocessor(observation)
        predicted = policy.select_action(processed_observation)
        predicted = postprocessor(predicted)

    predicted_values = [float(value) for value in predicted.squeeze(0).cpu().tolist()]
    recorded_values = [float(value) for value in frame["action"].cpu().tolist()]
    if len(predicted_values) != len(recorded_values):
        raise RuntimeError(
            f"action dimension mismatch: predicted={len(predicted_values)}, "
            f"recorded={len(recorded_values)}"
        )
    if not all(math.isfinite(value) for value in predicted_values):
        raise RuntimeError(f"policy produced non-finite action: {predicted_values}")

    action_feature = dataset.meta.features["action"]
    action_names = list(action_feature["names"])
    stats = dataset.meta.stats["action"]
    minimum = [float(value) for value in stats["min"]]
    maximum = [float(value) for value in stats["max"]]
    within_training_range = bounds_status(predicted_values, minimum, maximum)

    result = {
        "status": "PASS",
        "hardware_access": False,
        "device": str(device),
        "torch": torch.__version__,
        "policy_type": config.type,
        "checkpoint": str(args.checkpoint),
        "dataset_root": str(args.dataset_root),
        "dataset_episodes": dataset.num_episodes,
        "dataset_frames": dataset.num_frames,
        "frame_index": args.frame_index,
        "episode_index": scalar(frame["episode_index"]),
        "predicted_action": dict(zip(action_names, predicted_values, strict=True)),
        "recorded_action": dict(zip(action_names, recorded_values, strict=True)),
        "within_training_min_max": dict(zip(action_names, within_training_range, strict=True)),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
