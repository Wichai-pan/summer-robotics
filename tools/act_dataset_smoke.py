#!/usr/bin/env python3
"""No-hardware LeRobotDataset create -> save -> finalize -> reopen smoke test."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np

from act_episode_recorder import JOINT_NAMES, build_control_frame, dataset_features, CameraSample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="unique output directory; default is a temporary directory")
    args = parser.parse_args()
    root = args.root or Path(tempfile.mkdtemp(prefix="forestbridge-act-smoke-")) / "dataset"
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty directory: {root}")

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    repo_id = "forestbridge/act-dataset-smoke"
    fps, width, height = 10, 64, 48
    dataset = LeRobotDataset.create(
        repo_id=repo_id,
        root=root,
        fps=fps,
        features=dataset_features(width, height),
        robot_type="no_hardware_smoke",
        use_videos=True,
        video_backend="pyav",
        image_writer_threads=2,
    )
    zeros = {name: 0.0 for name in JOINT_NAMES}
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    for index in range(fps):
        rgb[:, :, 0] = index * 10
        sample = CameraSample(rgb=rgb.copy(), monotonic_s=index / fps, sequence=index)
        dataset.add_frame(
            build_control_frame(
                task="Dataset smoke test without hardware.",
                white_state=zeros,
                action=zeros,
                black_state=zeros,
                tracking_error=zeros,
                gemini=sample,
                wrist=sample,
                control_elapsed_s=index / fps,
                now_s=index / fps,
            )
        )
    dataset.save_episode()
    dataset.finalize()

    reopened = LeRobotDataset(
        repo_id=repo_id,
        root=root,
        video_backend="pyav",
        download_videos=False,
    )
    assert reopened.num_episodes == 1, reopened
    assert reopened.num_frames == fps, reopened
    assert set(dataset_features(width, height)) <= set(reopened.features)
    first = reopened.get_raw_item(0)
    assert len(first["observation.state"]) == 6
    assert len(first["action"]) == 6
    print(f"PASS create -> save_episode -> finalize -> reopen: {root}")
    print(f"episodes={reopened.num_episodes} frames={reopened.num_frames} fps={reopened.fps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
