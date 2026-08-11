import numpy as np
import pytest

from act_checkpoint_dry_run import (
    bounds_status,
    guarded_action,
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


def test_guarded_action_limits_training_range_and_step() -> None:
    values, reasons = guarded_action(
        predicted=[20.0, -4.0, 9.0],
        action_names=["shoulder_pan.pos", "wrist_roll.vel_deg_s", "gripper.pos"],
        action_minimum=[-10.0, -8.0, 0.5],
        action_maximum=[10.0, 8.0, 100.0],
        live_state=[2.0, 30.0, 1.0],
        state_names=["shoulder_pan.pos", "wrist_roll.pos", "gripper.pos"],
        max_arm_step_deg=1.0,
        max_gripper_step=2.0,
        max_wrist_speed_deg_s=1.0,
    )
    assert values == [3.0, -1.0, 3.0]
    assert reasons == {
        "shoulder_pan.pos": ["training_range", "single_step"],
        "wrist_roll.vel_deg_s": ["wrist_speed"],
        "gripper.pos": ["single_step"],
    }
