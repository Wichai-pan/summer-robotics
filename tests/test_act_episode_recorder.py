import numpy as np
import pytest

from act_episode_recorder import (
    ACTEpisodeRecorder,
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


class FakeDataset:
    def __init__(self) -> None:
        self.saved = 0
        self.finalized = 0
        self.cleared = 0
        self.num_episodes = 3

    def save_episode(self) -> None:
        self.saved += 1

    def finalize(self) -> None:
        self.finalized += 1

    def clear_episode_buffer(self) -> None:
        self.cleared += 1


class FakeCamera:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FailingClearDataset(FakeDataset):
    def clear_episode_buffer(self) -> None:
        self.cleared += 1
        raise RuntimeError("clear failed")


class FailingCamera(FakeCamera):
    def close(self) -> None:
        self.closed += 1
        raise RuntimeError("camera failed")


def test_freeze_recording_captures_boundary_without_saving_or_finalizing(
    tmp_path,
) -> None:
    recorder = object.__new__(ACTEpisodeRecorder)
    recorder.root = tmp_path / "dataset"
    recorder.task = "pick and hold v1"
    recorder.task_contract = "fixed_pick_hold/v1"
    recorder.scene_version = "scene-v1"
    recorder.dataset = FakeDataset()
    recorder.frame_count = 24
    recorder._closed = False
    recorder._recording_frozen = False
    recorder._recording_boundary = None

    recorder.freeze_recording(
        phase="holding",
        operator_event="h",
        human_result="pending",
        verification_basis="operator_boundary_only",
        end_snapshot={"action": [1, 2, 3, 4, 5, 6]},
        monotonic_s=12.5,
    )

    assert recorder.dataset.saved == 0
    assert recorder.dataset.finalized == 0
    assert not (recorder.root / "forestbridge" / "recording_boundaries.jsonl").exists()
    assert recorder._recording_boundary["captured_frames"] == 24
    assert recorder._recording_boundary["task_contract"] == "fixed_pick_hold/v1"
    with pytest.raises(RuntimeError, match="recording is frozen"):
        recorder.add_control_frame(
            white_state={},
            action={},
            black_state={},
            tracking_error={},
            control_elapsed_s=13.0,
        )


def test_delayed_finish_keeps_human_data_and_control_results_separate(tmp_path) -> None:
    recorder = object.__new__(ACTEpisodeRecorder)
    recorder.root = tmp_path / "dataset"
    recorder.task = "pick and hold v1"
    recorder.task_contract = "fixed_pick_hold/v1"
    recorder.scene_version = "scene-v1"
    recorder.dataset = FakeDataset()
    recorder.gemini = FakeCamera()
    recorder.wrist = FakeCamera()
    recorder.frame_count = 24
    recorder.fps = 20
    recorder._closed = False
    recorder._recording_frozen = False
    recorder._recording_boundary = None
    recorder._verify_reopen = lambda expected_episodes: None
    recorder.freeze_recording(
        phase="holding",
        operator_event="h",
        human_result="pending",
        verification_basis="operator_boundary_only",
        end_snapshot={"action": [1, 2, 3, 4, 5, 6]},
        monotonic_s=12.5,
    )

    result = recorder.finish(
        success=True,
        human_result="success",
        verification_basis="operator_confirmation_after_manual_place",
        control_session_result="completed",
    )

    assert recorder.dataset.saved == 1
    assert recorder.dataset.finalized == 1
    assert result["success"] is True
    assert result["human_result"] == "success"
    assert result["control_session_result"] == "completed"
    assert result["task_contract"] == "fixed_pick_hold/v1"
    assert result["recording_boundary"]["captured_frames"] == 24
    assert (recorder.root / "forestbridge" / "recording_boundaries.jsonl").is_file()


def test_pick_hold_cannot_save_without_a_recording_boundary(tmp_path) -> None:
    recorder = object.__new__(ACTEpisodeRecorder)
    recorder.root = tmp_path / "dataset"
    recorder.task = "pick and hold v1"
    recorder.task_contract = "fixed_pick_hold/v1"
    recorder.scene_version = "scene-v1"
    recorder.dataset = FakeDataset()
    recorder.frame_count = 24
    recorder.fps = 20
    recorder._closed = False
    recorder._recording_frozen = False
    recorder._recording_boundary = None

    with pytest.raises(RuntimeError, match="no frozen recording boundary"):
        recorder.finish(success=True)

    assert recorder.dataset.saved == 0


def test_abort_attempts_all_dataset_and_camera_cleanup_after_failures(tmp_path) -> None:
    recorder = object.__new__(ACTEpisodeRecorder)
    recorder.root = tmp_path / "dataset"
    recorder.task = "pick and hold v1"
    recorder.task_contract = "fixed_pick_hold/v1"
    recorder.scene_version = "scene-v1"
    recorder.dataset = FailingClearDataset()
    recorder.gemini = FailingCamera()
    recorder.wrist = FakeCamera()
    recorder.frame_count = 4
    recorder._closed = False
    recorder._recording_frozen = False
    recorder._recording_boundary = None
    recorder._recording_boundary_written = False

    with pytest.raises(RuntimeError, match="clear failed.*camera failed"):
        recorder.abort("test abort")

    assert recorder.dataset.cleared == 1
    assert recorder.dataset.finalized == 1
    assert recorder.gemini.closed == 1
    assert recorder.wrist.closed == 1
    assert recorder._closed is True
