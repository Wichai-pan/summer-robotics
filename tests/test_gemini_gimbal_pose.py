import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from gemini_gimbal_pose import (
    DEG_PER_TICK,
    encode_sign_magnitude,
    velocity_raw,
    wrapped_tick_delta,
)


def test_wrapped_tick_delta_uses_short_path_across_encoder_zero() -> None:
    assert wrapped_tick_delta(3, 4090) == 9
    assert wrapped_tick_delta(4090, 3) == -9


def test_wrapped_tick_delta_preserves_normal_direction() -> None:
    assert wrapped_tick_delta(1200, 1100) == 100
    assert wrapped_tick_delta(1100, 1200) == -100


def test_velocity_raw_has_deadband_and_cap() -> None:
    assert velocity_raw(0.4, 1.2, 4.0, 0.5) == 0
    assert velocity_raw(100.0, 1.2, 4.0, 0.5) == round(4.0 / DEG_PER_TICK)
    assert velocity_raw(-100.0, 1.2, 4.0, 0.5) == -round(4.0 / DEG_PER_TICK)


def test_sign_magnitude_encodes_negative_velocity_for_feetech() -> None:
    assert encode_sign_magnitude(46) == 46
    assert encode_sign_magnitude(-46) == (1 << 15) | 46
