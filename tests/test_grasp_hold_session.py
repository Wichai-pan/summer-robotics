import pytest

from grasp_hold_session import (
    ControlCycleCoordinator,
    GraspHoldSession,
    InvalidTransition,
    SessionEvent,
    SessionFault,
    SessionState,
    run_cleanup_actions,
    session_event_from_key,
)


JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "gripper",
)


def positions(value: float = 0.0) -> dict[str, float]:
    return {joint: value for joint in JOINTS}


class FakeWriter:
    def __init__(self) -> None:
        self.position_writes: list[dict[str, float]] = []
        self.wrist_writes: list[int] = []

    def write_position(self, command: dict[str, float]) -> None:
        self.position_writes.append(dict(command))

    def write_wrist_velocity(self, command_raw: int) -> None:
        self.wrist_writes.append(command_raw)


class FakeRecorder:
    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []
        self.boundaries: list[dict[str, object]] = []

    def add_control_frame(self, **frame: object) -> None:
        self.frames.append(frame)

    def freeze_recording(self, **boundary: object) -> None:
        self.boundaries.append(boundary)


class FailingFreezeRecorder(FakeRecorder):
    def freeze_recording(self, **boundary: object) -> None:
        raise RuntimeError("disk unavailable")


def test_end_recording_freezes_the_full_sent_target_without_closing_control() -> None:
    session = GraspHoldSession()
    feedback = positions(10.0)
    command = positions(10.5)

    update = session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=feedback,
        feedback_monotonic_s=2.0,
        position_command=command,
        wrist_target_deg=7.5,
    )

    assert session.state is SessionState.HOLDING
    assert update.freeze_recording is True
    assert update.close_control is False
    assert update.hold_target is not None
    assert update.hold_target.position_command == command
    assert update.hold_target.feedback == feedback
    assert update.hold_target.wrist_target_deg == 7.5


def test_hold_target_is_immune_to_later_leader_or_command_mutation() -> None:
    session = GraspHoldSession()
    feedback = positions(10.0)
    command = positions(10.5)
    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=feedback,
        feedback_monotonic_s=2.0,
        position_command=command,
        wrist_target_deg=7.5,
    )

    feedback["gripper"] = 0.0
    command["gripper"] = 100.0

    assert session.hold_target is not None
    assert session.hold_target.feedback["gripper"] == 10.0
    assert session.hold_target.position_command["gripper"] == 10.5


def test_placing_requires_an_explicit_event_and_requests_a_follow_rebase() -> None:
    session = GraspHoldSession()
    feedback = positions(10.0)
    command = positions(10.5)
    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=feedback,
        feedback_monotonic_s=2.0,
        position_command=command,
        wrist_target_deg=7.5,
    )

    update = session.apply_event(
        SessionEvent.BEGIN_PLACING,
        now_s=4.0,
        feedback=positions(10.2),
        feedback_monotonic_s=4.0,
        position_command=command,
        wrist_target_deg=7.5,
    )

    assert session.state is SessionState.PLACING
    assert update.rebase_follow is True
    assert update.close_control is False


def test_placement_confirmation_freezes_again_before_normal_exit() -> None:
    session = GraspHoldSession()
    feedback = positions(10.0)
    command = positions(10.5)
    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=feedback,
        feedback_monotonic_s=2.0,
        position_command=command,
        wrist_target_deg=7.5,
    )
    session.apply_event(
        SessionEvent.BEGIN_PLACING,
        now_s=4.0,
        feedback=feedback,
        feedback_monotonic_s=4.0,
        position_command=command,
        wrist_target_deg=7.5,
    )

    ready = session.apply_event(
        SessionEvent.PLACEMENT_COMPLETE,
        now_s=6.0,
        feedback=positions(12.0),
        feedback_monotonic_s=6.0,
        position_command=positions(12.25),
        wrist_target_deg=3.0,
    )
    closed = session.apply_event(
        SessionEvent.EXIT,
        now_s=7.0,
        feedback=positions(12.0),
        feedback_monotonic_s=7.0,
        position_command=positions(12.25),
        wrist_target_deg=3.0,
    )

    assert ready.state is SessionState.READY_TO_EXIT
    assert ready.hold_target is not None
    assert ready.hold_target.position_command == positions(12.25)
    assert closed.state is SessionState.CLOSED
    assert closed.close_control is True


def test_holding_timeout_fails_closed_at_the_existing_fifteen_second_limit() -> None:
    session = GraspHoldSession(max_hold_s=15.0)
    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=positions(10.0),
        feedback_monotonic_s=2.0,
        position_command=positions(10.0),
        wrist_target_deg=0.0,
    )

    with pytest.raises(SessionFault, match="hold exceeded 15.0s"):
        session.check_feedback(
            now_s=17.01,
            feedback_monotonic_s=17.01,
            feedback=positions(10.0),
            temperature_c=30.0,
            status_raw=0,
        )

    assert session.state is SessionState.FAULT


def test_ready_to_exit_remains_a_bounded_hold_state() -> None:
    session = GraspHoldSession(max_hold_s=15.0)
    snapshot = dict(
        feedback=positions(10.0),
        feedback_monotonic_s=2.0,
        position_command=positions(10.0),
        wrist_target_deg=0.0,
    )
    session.apply_event(SessionEvent.END_RECORDING_AND_HOLD, now_s=2.0, **snapshot)
    session.apply_event(SessionEvent.BEGIN_PLACING, now_s=3.0, **snapshot)
    session.apply_event(SessionEvent.PLACEMENT_COMPLETE, now_s=4.0, **snapshot)

    with pytest.raises(SessionFault, match="hold exceeded 15.0s"):
        session.check_feedback(
            now_s=19.01,
            feedback_monotonic_s=19.01,
            feedback=positions(10.0),
            temperature_c=30.0,
            status_raw=0,
        )


def test_stale_hold_feedback_enters_fault() -> None:
    session = GraspHoldSession(max_feedback_age_s=0.25)
    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=positions(10.0),
        feedback_monotonic_s=2.0,
        position_command=positions(10.0),
        wrist_target_deg=0.0,
    )

    with pytest.raises(SessionFault, match="feedback is stale"):
        session.check_feedback(
            now_s=3.0,
            feedback_monotonic_s=2.7,
            feedback=positions(10.0),
            temperature_c=30.0,
            status_raw=0,
        )

    assert session.state is SessionState.FAULT


def test_feedback_timestamp_regression_enters_fault() -> None:
    session = GraspHoldSession()
    session.check_feedback(
        now_s=2.0,
        feedback_monotonic_s=2.0,
        feedback=positions(),
        temperature_c=30.0,
        status_raw=0,
    )

    with pytest.raises(SessionFault, match="moved backwards"):
        session.check_feedback(
            now_s=2.1,
            feedback_monotonic_s=1.9,
            feedback=positions(),
            temperature_c=30.0,
            status_raw=0,
        )


@pytest.mark.parametrize(
    ("feedback", "temperature_c", "status_raw", "message"),
    [
        ({**positions(10.0), "elbow_flex": float("nan")}, 30.0, 0, "non-finite"),
        (positions(10.0), 60.0, 0, "temperature reached"),
        (positions(10.0), 30.0, 4, "status register"),
        ({**positions(10.0), "shoulder_lift": 26.0}, 30.0, 0, "tracking error"),
    ],
)
def test_hold_health_and_tracking_failures_enter_fault(
    feedback: dict[str, float],
    temperature_c: float,
    status_raw: int,
    message: str,
) -> None:
    session = GraspHoldSession(
        max_temperature_c=60.0,
        tracking_error=15.0,
        gripper_tracking_error=15.0,
    )
    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=positions(10.0),
        feedback_monotonic_s=2.0,
        position_command=positions(10.0),
        wrist_target_deg=0.0,
    )

    with pytest.raises(SessionFault, match=message):
        session.check_feedback(
            now_s=3.0,
            feedback_monotonic_s=3.0,
            feedback=feedback,
            temperature_c=temperature_c,
            status_raw=status_raw,
        )

    assert session.state is SessionState.FAULT


def test_safety_thresholds_cannot_exceed_existing_limits() -> None:
    with pytest.raises(ValueError, match="60"):
        GraspHoldSession(max_temperature_c=60.1)
    with pytest.raises(ValueError, match="15"):
        GraspHoldSession(max_hold_s=15.1)


@pytest.mark.parametrize(
    "advance",
    [
        [],
        [SessionEvent.END_RECORDING_AND_HOLD],
        [SessionEvent.END_RECORDING_AND_HOLD, SessionEvent.BEGIN_PLACING],
        [
            SessionEvent.END_RECORDING_AND_HOLD,
            SessionEvent.BEGIN_PLACING,
            SessionEvent.PLACEMENT_COMPLETE,
        ],
    ],
)
def test_explicit_stop_closes_control_from_every_active_state(
    advance: list[SessionEvent],
) -> None:
    session = GraspHoldSession()
    for event in advance:
        session.apply_event(
            event,
            now_s=float(len(session.events) + 1),
            feedback=positions(10.0),
            feedback_monotonic_s=float(len(session.events) + 1),
            position_command=positions(10.0),
            wrist_target_deg=0.0,
        )

    update = session.apply_event(
        SessionEvent.STOP,
        now_s=10.0,
        feedback=positions(10.0),
        feedback_monotonic_s=10.0,
        position_command=positions(10.0),
        wrist_target_deg=0.0,
    )

    assert update.state is SessionState.CLOSED
    assert update.close_control is True
    assert session.control_result == "operator_stop"


def test_duplicate_and_out_of_order_events_are_rejected() -> None:
    session = GraspHoldSession()
    with pytest.raises(InvalidTransition):
        session.apply_event(
            SessionEvent.BEGIN_PLACING,
            now_s=1.0,
            feedback=positions(),
            feedback_monotonic_s=1.0,
            position_command=positions(),
            wrist_target_deg=0.0,
        )

    session.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=positions(),
        feedback_monotonic_s=2.0,
        position_command=positions(),
        wrist_target_deg=0.0,
    )
    with pytest.raises(InvalidTransition):
        session.apply_event(
            SessionEvent.END_RECORDING_AND_HOLD,
            now_s=3.0,
            feedback=positions(),
            feedback_monotonic_s=3.0,
            position_command=positions(),
            wrist_target_deg=0.0,
        )


def test_recording_boundary_stops_frames_but_keeps_full_arm_control_running() -> None:
    session = GraspHoldSession()
    writer = FakeWriter()
    recorder = FakeRecorder()
    coordinator = ControlCycleCoordinator(session, writer, recorder)
    frame = {"action": positions(10.0)}

    coordinator.execute_cycle(
        now_s=1.0,
        feedback_monotonic_s=1.0,
        feedback=positions(10.0),
        temperature_c=30.0,
        status_raw=0,
        position_command=positions(10.0),
        wrist_velocity_raw=4,
        record_frame=frame,
    )
    coordinator.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        now_s=2.0,
        feedback=positions(10.0),
        feedback_monotonic_s=2.0,
        position_command=positions(10.0),
        wrist_target_deg=2.0,
        boundary={"phase": "holding", "operator_event": "h"},
    )
    coordinator.execute_cycle(
        now_s=2.1,
        feedback_monotonic_s=2.1,
        feedback=positions(10.0),
        temperature_c=30.0,
        status_raw=0,
        position_command=positions(10.0),
        wrist_velocity_raw=-2,
        record_frame={"action": positions(99.0)},
    )

    assert len(recorder.frames) == 1
    assert recorder.boundaries == [{"phase": "holding", "operator_event": "h"}]
    assert writer.position_writes == [positions(10.0), positions(10.0)]
    assert writer.wrist_writes == [4, -2]


def test_cleanup_attempts_every_action_after_an_earlier_failure() -> None:
    calls: list[str] = []

    def fail_zero() -> None:
        calls.append("zero_wrist")
        raise RuntimeError("write failed")

    def succeed(name: str):
        def action() -> None:
            calls.append(name)

        return action

    errors = run_cleanup_actions(
        [
            ("zero wrist", fail_zero),
            ("disable torque", succeed("disable_torque")),
            ("restore wrist mode", succeed("restore_mode")),
            ("disconnect white", succeed("disconnect_white")),
            ("disconnect black", succeed("disconnect_black")),
        ]
    )

    assert calls == [
        "zero_wrist",
        "disable_torque",
        "restore_mode",
        "disconnect_white",
        "disconnect_black",
    ]
    assert errors == ["zero wrist: write failed"]


def test_control_write_failure_marks_session_fault() -> None:
    class FailingWriter(FakeWriter):
        def write_position(self, command: dict[str, float]) -> None:
            raise RuntimeError("communication failed")

    session = GraspHoldSession()
    coordinator = ControlCycleCoordinator(session, FailingWriter(), None)

    with pytest.raises(SessionFault, match="communication failed"):
        coordinator.execute_cycle(
            now_s=1.0,
            feedback_monotonic_s=1.0,
            feedback=positions(),
            temperature_c=30.0,
            status_raw=0,
            position_command=positions(),
            wrist_velocity_raw=0,
            record_frame=None,
        )

    assert session.state is SessionState.FAULT


def test_recording_boundary_failure_marks_session_fault() -> None:
    session = GraspHoldSession()
    coordinator = ControlCycleCoordinator(session, FakeWriter(), FailingFreezeRecorder())

    with pytest.raises(SessionFault, match="recording boundary failed"):
        coordinator.apply_event(
            SessionEvent.END_RECORDING_AND_HOLD,
            boundary={"phase": "holding"},
            now_s=1.0,
            feedback=positions(),
            feedback_monotonic_s=1.0,
            position_command=positions(),
            wrist_target_deg=0.0,
        )

    assert session.state is SessionState.FAULT


def test_hold_session_keys_keep_record_boundary_distinct_from_stop() -> None:
    assert session_event_from_key("h") is SessionEvent.END_RECORDING_AND_HOLD
    assert session_event_from_key("p") is SessionEvent.BEGIN_PLACING
    assert session_event_from_key("d") is SessionEvent.PLACEMENT_COMPLETE
    assert session_event_from_key("x") is SessionEvent.EXIT
    assert session_event_from_key("q") is SessionEvent.STOP
    assert session_event_from_key("\x1b") is SessionEvent.STOP
    assert session_event_from_key("z") is None
