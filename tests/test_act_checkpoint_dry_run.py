import numpy as np
import pytest

from act_checkpoint_dry_run import (
    bounds_status,
    parse_frame_indices,
    rgb_to_policy_tensor,
    state_values,
)


def test_bounds_status_is_inclusive_and_dimensionwise() -> None:
    assert bounds_status([0.0, 2.0, 5.0], [0.0, 1.0, 3.0], [1.0, 2.0, 4.0]) == [
        True,
        True,
        False,
    ]


def test_parse_frame_indices() -> None:
    assert parse_frame_indices(None, 7) == [7]
    assert parse_frame_indices("0, 12,24", 7) == [0, 12, 24]


def test_rgb_to_policy_tensor() -> None:
    rgb = np.full((2, 3, 3), 255, dtype=np.uint8)
    tensor = rgb_to_policy_tensor(rgb)
    assert tuple(tensor.shape) == (3, 2, 3)
    assert tensor.min().item() == pytest.approx(1.0)


def test_state_values_follows_feature_order() -> None:
    state = {"elbow_flex": 3.0, "shoulder_pan": 1.0}
    assert state_values(state, ["shoulder_pan.pos", "elbow_flex.pos"]) == [1.0, 3.0]
