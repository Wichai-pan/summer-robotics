import pytest

from tools.nav2_supervised_base_execute import (
    advance_waypoint_index,
    path_alignment_progress,
    validate_rotate_only_feedback,
)


def test_rotate_only_feedback_cannot_advance_waypoint() -> None:
    points = [(0.02, -0.04, 0.0), (0.10, -0.05, 0.0), (0.18, -0.04, 0.0)]

    waypoint_index = advance_waypoint_index(
        points,
        0.11,
        -0.04,
        0,
        0.07,
        allow_translation_progress=False,
    )

    assert waypoint_index == 0


def test_rotate_only_distance_reduction_is_not_progress() -> None:
    made_progress, best_distance, best_heading = path_alignment_progress(
        0.680,
        0.700,
        -22.0,
        23.0,
        feedback_mode="rotate",
    )

    assert made_progress is False
    assert best_distance == 0.700
    assert best_heading == 23.0


def test_rotate_only_heading_improvement_is_progress() -> None:
    made_progress, best_distance, best_heading = path_alignment_progress(
        0.680,
        0.700,
        -17.0,
        23.0,
        feedback_mode="rotate",
    )

    assert made_progress is True
    assert best_distance == 0.700
    assert best_heading == 17.0


def test_stopped_feedback_does_not_count_visual_drift_as_progress() -> None:
    made_progress, best_distance, best_heading = path_alignment_progress(
        0.650,
        0.700,
        -12.0,
        23.0,
        feedback_mode="stopped",
    )

    assert made_progress is False
    assert best_distance == 0.700
    assert best_heading == 23.0


def test_20260818_rotate_only_trace_aborts_on_false_translation() -> None:
    # Reduced from nav2-supervised-execute/20260818T210216Z. Every pose after
    # the anchor was observed while the command still had linear_mps == 0.
    anchor = (0.0170, -0.0132)
    rotate_only_poses = [
        (0.0168, -0.0134),
        (0.0183, -0.0139),
        (0.0314, -0.0079),
        (0.0489, 0.0076),
        (0.0573, 0.0059),
        (0.0703, 0.0043),
    ]

    for current_x, current_y in rotate_only_poses[:-1]:
        validate_rotate_only_feedback(anchor, current_x, current_y, 0.05)

    with pytest.raises(RuntimeError, match="camera-only base feedback is inconsistent"):
        validate_rotate_only_feedback(anchor, *rotate_only_poses[-1], 0.05)
