from __future__ import annotations

import time

import numpy as np
import pytest

from forestbridge_shared_rgb import SharedRGBError, SharedRGBReader, SharedRGBWriter


def test_atomic_shared_rgb_round_trip(tmp_path) -> None:
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[:, :, 0] = 180
    writer = SharedRGBWriter(tmp_path, max_hz=20, jpeg_quality=95)
    assert writer.offer(rgb)

    frame = SharedRGBReader(
        tmp_path, expected_width=64, expected_height=48
    ).latest(max_age_s=1.0)

    assert frame.sequence == 1
    assert frame.rgb.shape == rgb.shape
    assert frame.rgb.dtype == np.uint8
    assert float(frame.rgb[:, :, 0].mean()) > 170


def test_writer_rate_limit_keeps_sequence_stable(tmp_path) -> None:
    writer = SharedRGBWriter(tmp_path, max_hz=2)
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    assert writer.offer(rgb, monotonic_s=10.0)
    assert not writer.offer(rgb, monotonic_s=10.1)
    assert writer.sequence == 1


def test_reader_rejects_stale_frame(tmp_path) -> None:
    writer = SharedRGBWriter(tmp_path)
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    assert writer.offer(rgb, monotonic_s=time.monotonic() - 2.0)
    with pytest.raises(SharedRGBError, match="stale"):
        SharedRGBReader(tmp_path).latest(max_age_s=0.5)


def test_reader_rejects_corrupt_image(tmp_path) -> None:
    writer = SharedRGBWriter(tmp_path)
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    assert writer.offer(rgb)
    (tmp_path / "latest.jpg").write_bytes(b"corrupt")
    with pytest.raises(SharedRGBError, match="cannot read"):
        SharedRGBReader(tmp_path).latest(max_age_s=1.0)
