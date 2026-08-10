import numpy as np

from act_episode_recorder import (
    ACTION_NAMES,
    JOINT_NAMES,
    CameraSample,
    build_control_frame,
    dataset_features,
    duplicate_frame_limit,
    feature_specs_match,
)


def values(offset: float = 0.0) -> dict[str, float]:
    return {name: index + offset for index, name in enumerate(JOINT_NAMES)}


def test_dataset_schema_keeps_wrist_velocity_semantics_explicit() -> None:
    features = dataset_features(width=640, height=480)
    assert features["observation.state"]["shape"] == (6,)
    assert features["action"]["names"] == list(ACTION_NAMES)
    assert features["action"]["names"][4] == "wrist_roll.vel_deg_s"
    assert features["observation.images.gemini_rgb"]["shape"] == (480, 640, 3)
    assert features["observation.images.white_wrist_rgb"]["dtype"] == "video"


def test_feature_comparison_accepts_json_list_shape() -> None:
    expected = dataset_features(width=640, height=480)["action"]
    loaded = {**expected, "shape": [6]}
    assert feature_specs_match(loaded, expected)


def test_duplicate_limit_defers_to_camera_freshness_window() -> None:
    assert duplicate_frame_limit(control_fps=20, max_camera_age_s=0.25) == 5
    assert duplicate_frame_limit(control_fps=10, max_camera_age_s=0.05) == 2


def test_build_control_frame_has_synchronized_numeric_and_rgb_values() -> None:
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    gemini = CameraSample(image, monotonic_s=9.90, sequence=12)
    wrist = CameraSample(image.copy(), monotonic_s=9.95, sequence=21)
    frame = build_control_frame(
        task="fixed pick and place",
        white_state=values(1.0),
        action=values(2.0),
        black_state=values(3.0),
        tracking_error=values(4.0),
        gemini=gemini,
        wrist=wrist,
        control_elapsed_s=1.25,
        now_s=10.0,
    )
    assert frame["observation.state"].dtype == np.float32
    assert frame["action"].shape == (6,)
    assert frame["observation.images.gemini_rgb"].shape == (48, 64, 3)
    assert frame["diagnostic.camera_sequence"].tolist() == [12, 21]
    np.testing.assert_allclose(frame["diagnostic.camera_age_s"], [0.10, 0.05], atol=1e-6)
    assert frame["task"] == "fixed pick and place"
