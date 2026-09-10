#!/usr/bin/env python3
"""Atomic JPEG exchange for one camera producer and many local consumers.

The producer owns the physical camera.  Consumers read the newest frame from a
host-shared directory and therefore never need the USB device or its lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np


FORMAT_VERSION = 1


class SharedRGBError(RuntimeError):
    """The shared frame is absent, stale, corrupt, or has the wrong shape."""


@dataclass(frozen=True)
class SharedRGBFrame:
    rgb: Any
    monotonic_s: float
    sequence: int


@dataclass(frozen=True)
class SharedJPEGFrame:
    jpeg: bytes
    monotonic_s: float
    sequence: int
    width: int
    height: int


class SharedRGBWriter:
    def __init__(
        self,
        directory: str | Path,
        *,
        max_hz: float = 10.0,
        jpeg_quality: int = 90,
    ) -> None:
        if max_hz <= 0 or not 1 <= jpeg_quality <= 100:
            raise ValueError("max_hz and jpeg_quality must be positive")
        self.directory = Path(directory)
        self.image_path = self.directory / "latest.jpg"
        self.metadata_path = self.directory / "latest.json"
        self.minimum_interval_s = 1.0 / float(max_hz)
        self.jpeg_quality = int(jpeg_quality)
        self.sequence = 0
        self.last_write_s = float("-inf")

    def offer(self, rgb: Any, *, monotonic_s: float | None = None) -> bool:
        import cv2
        import numpy as np

        now_s = time.monotonic() if monotonic_s is None else float(monotonic_s)
        if now_s - self.last_write_s < self.minimum_interval_s:
            return False
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError(f"expected HxWx3 uint8 RGB, got {rgb.shape}/{rgb.dtype}")
        bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(
            ".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        )
        if not ok:
            raise SharedRGBError("JPEG encoding failed")
        payload = encoded.tobytes()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sequence += 1
        token = f"{os.getpid()}-{self.sequence}"
        temporary_image = self.directory / f".latest-{token}.jpg"
        temporary_metadata = self.directory / f".latest-{token}.json"
        metadata = {
            "version": FORMAT_VERSION,
            "sequence": self.sequence,
            "monotonic_s": now_s,
            "height": int(rgb.shape[0]),
            "width": int(rgb.shape[1]),
            "encoding": "rgb8",
            "jpeg_sha256": hashlib.sha256(payload).hexdigest(),
        }
        temporary_image.write_bytes(payload)
        temporary_metadata.write_text(
            json.dumps(metadata, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary_image, self.image_path)
        os.replace(temporary_metadata, self.metadata_path)
        self.last_write_s = now_s
        return True


class SharedRGBReader:
    def __init__(
        self,
        directory: str | Path,
        *,
        expected_width: int | None = None,
        expected_height: int | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.image_path = self.directory / "latest.jpg"
        self.metadata_path = self.directory / "latest.json"
        self.expected_width = expected_width
        self.expected_height = expected_height

    def latest_jpeg(self, max_age_s: float) -> SharedJPEGFrame:
        if max_age_s <= 0:
            raise ValueError("max_age_s must be positive")
        last_error: BaseException | None = None
        for _ in range(3):
            try:
                metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                payload = self.image_path.read_bytes()
                if metadata.get("version") != FORMAT_VERSION:
                    raise SharedRGBError("unsupported shared-frame version")
                if hashlib.sha256(payload).hexdigest() != metadata.get("jpeg_sha256"):
                    raise SharedRGBError("shared JPEG changed during read")
                timestamp = float(metadata["monotonic_s"])
                age_s = time.monotonic() - timestamp
                if age_s < -1.0 or age_s > max_age_s:
                    raise SharedRGBError(
                        f"shared Gemini frame is stale: age={age_s:.3f}s > {max_age_s:.3f}s"
                    )
                height, width = int(metadata["height"]), int(metadata["width"])
                if self.expected_width is not None and width != self.expected_width:
                    raise SharedRGBError(
                        f"shared Gemini width is {width}, expected {self.expected_width}"
                    )
                if self.expected_height is not None and height != self.expected_height:
                    raise SharedRGBError(
                        f"shared Gemini height is {height}, expected {self.expected_height}"
                    )
                return SharedJPEGFrame(
                    jpeg=payload,
                    monotonic_s=timestamp,
                    sequence=int(metadata["sequence"]),
                    width=width,
                    height=height,
                )
            except (
                KeyError,
                OSError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                SharedRGBError,
            ) as exc:
                last_error = exc
                time.sleep(0.005)
        raise SharedRGBError(f"cannot read shared Gemini frame: {last_error}")

    def latest(self, max_age_s: float) -> SharedRGBFrame:
        import cv2
        import numpy as np

        encoded = self.latest_jpeg(max_age_s)
        bgr = cv2.imdecode(np.frombuffer(encoded.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise SharedRGBError("shared JPEG decode failed")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if rgb.shape[:2] != (encoded.height, encoded.width):
            raise SharedRGBError("shared JPEG shape disagrees with metadata")
        return SharedRGBFrame(
            rgb=np.ascontiguousarray(rgb),
            monotonic_s=encoded.monotonic_s,
            sequence=encoded.sequence,
        )
