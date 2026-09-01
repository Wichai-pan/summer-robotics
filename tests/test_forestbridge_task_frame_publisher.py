from __future__ import annotations

import importlib.util
import os
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "forestbridge_task_frame_publisher.py"
SPEC = importlib.util.spec_from_file_location("forestbridge_task_frame_publisher", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeFrame:
    def copy(self):
        return self


def test_task_preview_is_disabled_without_private_environment() -> None:
    previous = os.environ.pop("FORESTBRIDGE_TASK_PREVIEW", None)
    try:
        publisher = MODULE.TaskFramePublisher(relay_url="", token="")
        assert publisher.enabled is False
        publisher.offer("gemini", FakeFrame())
        publisher.close()
    finally:
        if previous is not None:
            os.environ["FORESTBRIDGE_TASK_PREVIEW"] = previous


def test_task_preview_selects_explicit_and_preferred_sources() -> None:
    publisher = MODULE.TaskFramePublisher(
        relay_url="https://example.invalid",
        token="token",
        preferred_sources=("wrist_white", "gemini"),
    )
    publisher.enabled = True
    publisher.offer("gemini", FakeFrame())
    publisher.offer("wrist_white", FakeFrame())
    assert publisher._select_source({"source": "gemini"})[0] == "gemini"
    assert publisher._select_source({"source": "auto"})[0] == "wrist_white"
