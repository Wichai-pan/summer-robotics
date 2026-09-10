#!/usr/bin/env python3
"""Run an existing policy script with Gemini sourced from the RGB broker.

The adapter patches only the imported ``GeminiRGBSource`` symbol in memory.
It deliberately leaves ``act_episode_recorder.py`` untouched because current
team branches extend that module independently.
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
import time
from pathlib import Path
from typing import Any

import act_episode_recorder as recorder
from forestbridge_shared_rgb import SharedRGBError, SharedRGBReader


class SharedGeminiRGBSource(recorder.LatestRGBSource):
    def __init__(self, width: int, height: int, fps: int) -> None:
        super().__init__("gemini_rgb", width, height, fps)
        directory = os.environ.get(
            "FORESTBRIDGE_GEMINI_SHARED_DIR", "/dev/shm/forestbridge-gemini"
        )
        self.reader = SharedRGBReader(
            directory, expected_width=width, expected_height=height
        )
        self.identity: dict[str, Any] = {
            "name": self.name,
            "transport": "host-shared-jpeg",
            "directory": directory,
            "width": width,
            "height": height,
            "fps": fps,
        }

    def _open(self) -> None:
        # The persistent broker already owns and warms the physical camera.
        self.reader.latest(max_age_s=1.0)

    def _capture_loop(self) -> None:
        last_sequence = -1
        while not self._stop.is_set():
            try:
                frame = self.reader.latest(max_age_s=1.0)
            except SharedRGBError:
                time.sleep(0.02)
                continue
            if frame.sequence != last_sequence:
                self._publish(frame.rgb, frame.monotonic_s, frame.sequence)
                last_sequence = frame.sequence
            time.sleep(0.01)

    def _close(self) -> None:
        return None


class TaskInjectingProcessor:
    def __init__(self, processor: Any, task: str) -> None:
        self.processor = processor
        self.task = task

    def __call__(self, observation: dict[str, Any]) -> Any:
        if "task" not in observation:
            observation = {**observation, "task": [self.task]}
        return self.processor(observation)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.processor, name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--task", required=True)
    args, script_args = parser.parse_known_args()
    if not args.script.is_file():
        raise SystemExit(f"policy script is missing: {args.script}")

    recorder.GeminiRGBSource = SharedGeminiRGBSource
    from lerobot.policies import factory

    original_make_processors = factory.make_pre_post_processors

    def make_processors_with_task(*factory_args: Any, **factory_kwargs: Any) -> Any:
        preprocessor, postprocessor = original_make_processors(
            *factory_args, **factory_kwargs
        )
        return TaskInjectingProcessor(preprocessor, args.task), postprocessor

    factory.make_pre_post_processors = make_processors_with_task
    sys.argv = [str(args.script), *script_args]
    runpy.run_path(str(args.script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
