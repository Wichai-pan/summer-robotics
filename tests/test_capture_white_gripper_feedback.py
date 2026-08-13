import pytest

from capture_white_gripper_feedback import (
    LABEL_TARGETS,
    converted_feedback,
    slew_value,
    summarize_samples,
)


def test_physical_white_gripper_direction_matches_field_observation() -> None:
    assert LABEL_TARGETS["open"] == 60.0
    assert LABEL_TARGETS["empty_close"] == 5.0
    assert LABEL_TARGETS["grasp"] == 5.0
    assert LABEL_TARGETS["slip"] == 5.0
    assert LABEL_TARGETS["open"] > LABEL_TARGETS["empty_close"]


def test_feedback_unit_conversions_preserve_sign_where_applicable() -> None:
    converted = converted_feedback(-10, -250, 20)
    assert converted["velocity_nominal_deg_s"] == pytest.approx(-0.87890625)
    assert converted["load_abs_percent"] == pytest.approx(25.0)
    assert converted["current_estimated_ma"] == pytest.approx(130.0)


def test_slew_value_never_overshoots() -> None:
    assert slew_value(5.0, 60.0, 2.0) == 7.0
    assert slew_value(59.0, 60.0, 2.0) == 60.0
    assert slew_value(10.0, 5.0, 2.0) == 8.0


def test_summary_prefers_hold_samples() -> None:
    base = {
        "position_error_normalized": 1.0,
        "present_velocity_raw": 2,
        "present_load_raw": 3,
        "present_load_abs_percent": 0.3,
        "present_current_raw": 4,
        "present_current_estimated_ma": 26.0,
    }
    samples = [
        {**base, "phase": "motion", "present_current_raw": 100},
        {**base, "phase": "hold", "present_current_raw": 4},
        {**base, "phase": "hold", "present_current_raw": 6},
    ]
    summary = summarize_samples(samples)
    assert summary["sample_count"] == 3
    assert summary["hold_sample_count"] == 2
    assert summary["hold_or_all"]["present_current_raw"]["median"] == 5
