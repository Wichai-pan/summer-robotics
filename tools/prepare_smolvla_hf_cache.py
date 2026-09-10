#!/usr/bin/env python3
"""Populate the persistent Hugging Face cache required by Jetson SmolVLA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-id",
        default="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/data/cache/huggingface/hub"),
    )
    parser.add_argument("--revision")
    args = parser.parse_args()

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_download(
        repo_id=args.repo_id,
        revision=args.revision,
        cache_dir=str(args.cache_dir),
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "repo_id": args.repo_id,
                "revision": args.revision,
                "snapshot": snapshot,
                "cache_dir": str(args.cache_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
