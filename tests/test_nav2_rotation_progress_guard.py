import pytest

from tools.nav2_supervised_base_execute import (
    STOP_BUS_SETTLE_S,
    STOP_READBACK_PERIOD_S,
    advance_waypoint_index,
    brake_and_verify_release,
    path_alignment_progress,
    rotation_progress_baseline,
    validate_rotate_only_feedback,
    write_and_verify_byte,
)


class FakeTorquePacket:
    def __init__(self) -> None:
        self.value = 1
        self.writes = 0

    def write1ByteTxOnly(self, _port: object, _motor_id: int, _address: int, value: int) -> int:
        self.writes += 1
        if self.writes >= 2:
            self.value = value
        return 0

    def read1ByteTxRx(self, _port: object, _motor_id: int, _address: int) -> tuple[int, int, int]:
        return self.value, 0, 0


class ExplodingTorquePacket:
    def __init__(self) -> None:
        self.attempted_ids: list[int] = []

    def write1ByteTxOnly(
        self, _port: object, motor_id: int, _address: int, _value: int
    ) -> int:
        self.attempted_ids.append(motor_id)
        raise RuntimeError("injected SDK failure")


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


def test_new_path_rotation_resets_heading_progress_baseline() -> None:
    # A previous segment may have converged to 2 degrees. A later 70-degree
    # turn must not inherit that old best value or it can never show progress.
    baseline = rotation_progress_baseline("translate", "rotate", -70.0, 2.0)

    assert baseline == 70.0


def test_continuing_rotation_keeps_current_heading_progress_baseline() -> None:
    baseline = rotation_progress_baseline("rotate", "rotate", -50.0, 55.0)

    assert baseline == 55.0


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


def test_torque_off_uses_tx_only_then_independent_readback() -> None:
    packet = FakeTorquePacket()

    error = write_and_verify_byte(packet, object(), 7, 40, 0, 0, "disable torque")

    assert error is None
    assert packet.writes == 2


def test_shutdown_attempts_every_motor_when_sdk_write_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    packet = ExplodingTorquePacket()
    monkeypatch.setattr("tools.nav2_supervised_base_execute.time.sleep", lambda _seconds: None)

    report, errors = brake_and_verify_release(
        packet,
        object(),
        object(),
        0,
        0.0,
        write_zero=lambda *_args: None,
        read_wheels=lambda *_args: {"wheels": {}},
        stop_readback_confirmed=lambda _samples: True,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )

    assert set(packet.attempted_ids) == {7, 8, 9}
    assert len(errors) == 3
    assert report["stop_readback_confirmed"] is True


def test_shutdown_readback_cadence_leaves_bus_recovery_time() -> None:
    assert STOP_BUS_SETTLE_S >= 0.2
    assert STOP_READBACK_PERIOD_S >= 0.5
