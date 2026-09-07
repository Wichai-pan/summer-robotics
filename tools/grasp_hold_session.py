#!/usr/bin/env python3
"""Pure lifecycle logic for an opt-in record, hold, and place session.

This module has no ROS, camera, serial, motor, Docker, or LeRobot imports.  A
hardware-owning caller supplies fresh feedback and the command it actually
sent.  The state machine decides when recording stops and which control mode
remains active; it never writes hardware itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable, Iterable
from typing import Protocol


class SessionState(str, Enum):
    RECORDING = "recording"
    HOLDING = "holding"
    PLACING = "placing"
    READY_TO_EXIT = "ready_to_exit"
    CLOSED = "closed"
    FAULT = "fault"


class SessionEvent(str, Enum):
    END_RECORDING_AND_HOLD = "end_recording_and_hold"
    BEGIN_PLACING = "begin_placing"
    PLACEMENT_COMPLETE = "placement_complete"
    EXIT = "exit"
    STOP = "stop"


def session_event_from_key(key: str) -> SessionEvent | None:
    return {
        "h": SessionEvent.END_RECORDING_AND_HOLD,
        "p": SessionEvent.BEGIN_PLACING,
        "d": SessionEvent.PLACEMENT_COMPLETE,
        "x": SessionEvent.EXIT,
        "q": SessionEvent.STOP,
        "\x1b": SessionEvent.STOP,
    }.get(key.lower())


class InvalidTransition(RuntimeError):
    """The requested operator event is not valid in the current state."""


class SessionFault(RuntimeError):
    """A safety invariant failed and the control session must stop."""


@dataclass(frozen=True)
class HoldTarget:
    position_command: dict[str, float]
    feedback: dict[str, float]
    wrist_target_deg: float
    captured_monotonic_s: float


@dataclass(frozen=True)
class SessionUpdate:
    state: SessionState
    freeze_recording: bool = False
    rebase_follow: bool = False
    close_control: bool = False
    hold_target: HoldTarget | None = None


class ControlWriter(Protocol):
    def write_position(self, command: dict[str, float]) -> None: ...

    def write_wrist_velocity(self, command_raw: int) -> None: ...


class RecordingSink(Protocol):
    def add_control_frame(self, **frame: object) -> None: ...

    def freeze_recording(self, **boundary: object) -> None: ...


def _finite_values(label: str, values: dict[str, float]) -> None:
    invalid = [name for name, value in values.items() if not math.isfinite(value)]
    if invalid:
        raise SessionFault(f"{label} contains non-finite joints: {invalid}")


def run_cleanup_actions(
    actions: Iterable[tuple[str, Callable[[], None]]],
) -> list[str]:
    """Attempt every required cleanup action and report all failures."""
    errors: list[str] = []
    for label, action in actions:
        try:
            action()
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    return errors


class GraspHoldSession:
    """Separate recording lifetime from the torque-enabled control lifetime."""

    def __init__(
        self,
        *,
        max_hold_s: float = 15.0,
        max_feedback_age_s: float = 0.25,
        max_temperature_c: float = 60.0,
        tracking_error: float = 15.0,
        gripper_tracking_error: float = 15.0,
    ) -> None:
        if not math.isfinite(max_hold_s) or not 0 < max_hold_s <= 15.0:
            raise ValueError("max_hold_s must be finite and in (0, 15]")
        if not math.isfinite(max_feedback_age_s) or max_feedback_age_s <= 0:
            raise ValueError("max_feedback_age_s must be finite and positive")
        if not math.isfinite(max_temperature_c) or not 0 < max_temperature_c <= 60.0:
            raise ValueError("max_temperature_c must be finite and in (0, 60]")
        if not math.isfinite(tracking_error) or tracking_error <= 0:
            raise ValueError("tracking_error must be finite and positive")
        if not math.isfinite(gripper_tracking_error) or gripper_tracking_error <= 0:
            raise ValueError("gripper_tracking_error must be finite and positive")
        self.state = SessionState.RECORDING
        self.hold_target: HoldTarget | None = None
        self.max_hold_s = max_hold_s
        self.max_feedback_age_s = max_feedback_age_s
        self.max_temperature_c = max_temperature_c
        self.tracking_error = tracking_error
        self.gripper_tracking_error = gripper_tracking_error
        self.fault_reason: str | None = None
        self.control_result: str | None = None
        self.events: list[dict[str, object]] = []
        self._last_feedback_monotonic_s: float | None = None

    def _record_event(
        self,
        event: SessionEvent | str,
        *,
        now_s: float | None,
        previous_state: SessionState,
    ) -> None:
        self.events.append(
            {
                "event": event.value if isinstance(event, SessionEvent) else event,
                "from_state": previous_state.value,
                "state": self.state.value,
                "monotonic_s": now_s,
            }
        )

    def _fault(self, reason: str, *, now_s: float | None = None) -> None:
        previous = self.state
        self.state = SessionState.FAULT
        self.fault_reason = reason
        self.control_result = "fault"
        self._record_event("fault", now_s=now_s, previous_state=previous)
        raise SessionFault(reason)

    def fail(self, reason: str, *, now_s: float | None = None) -> None:
        self._fault(reason, now_s=now_s)

    def check_feedback(
        self,
        *,
        now_s: float,
        feedback_monotonic_s: float,
        feedback: dict[str, float],
        temperature_c: float,
        status_raw: int,
    ) -> None:
        if not all(
            math.isfinite(value)
            for value in (now_s, feedback_monotonic_s, temperature_c)
        ):
            self._fault("feedback health contains a non-finite value", now_s=now_s)
        try:
            _finite_values("feedback", feedback)
        except SessionFault as exc:
            self._fault(str(exc), now_s=now_s)
        if now_s < feedback_monotonic_s:
            self._fault("feedback timestamp is in the future", now_s=now_s)
        if (
            self._last_feedback_monotonic_s is not None
            and feedback_monotonic_s < self._last_feedback_monotonic_s
        ):
            self._fault("feedback timestamp moved backwards", now_s=now_s)
        self._last_feedback_monotonic_s = feedback_monotonic_s
        age_s = now_s - feedback_monotonic_s
        if age_s > self.max_feedback_age_s:
            self._fault(
                f"feedback is stale: age={age_s:.3f}s > {self.max_feedback_age_s:.3f}s",
                now_s=now_s,
            )
        if temperature_c >= self.max_temperature_c:
            self._fault(
                f"gripper temperature reached {temperature_c:.1f}C "
                f">= {self.max_temperature_c:.1f}C",
                now_s=now_s,
            )
        if status_raw != 0:
            self._fault(
                f"gripper status register is nonzero ({status_raw})", now_s=now_s
            )
        if self.state in (SessionState.HOLDING, SessionState.READY_TO_EXIT):
            assert self.hold_target is not None
            if now_s - self.hold_target.captured_monotonic_s > self.max_hold_s:
                self._fault(f"hold exceeded {self.max_hold_s:.1f}s", now_s=now_s)
        if self.state in (SessionState.HOLDING, SessionState.READY_TO_EXIT):
            assert self.hold_target is not None
            if set(feedback) != set(self.hold_target.position_command):
                self._fault("feedback joints differ from the hold target", now_s=now_s)
            for joint, target in self.hold_target.position_command.items():
                limit = (
                    self.gripper_tracking_error
                    if joint == "gripper"
                    else self.tracking_error
                )
                error = abs(target - feedback[joint])
                if error > limit:
                    self._fault(
                        f"hold tracking error {error:.1f} on {joint} exceeds {limit:.1f}",
                        now_s=now_s,
                    )

    @staticmethod
    def _capture_hold_target(
        *,
        now_s: float,
        feedback: dict[str, float],
        feedback_monotonic_s: float,
        position_command: dict[str, float],
        wrist_target_deg: float,
    ) -> HoldTarget:
        _finite_values("feedback", feedback)
        _finite_values("position command", position_command)
        if not all(
            math.isfinite(value)
            for value in (now_s, feedback_monotonic_s, wrist_target_deg)
        ):
            raise SessionFault("hold boundary contains a non-finite value")
        return HoldTarget(
            position_command=dict(position_command),
            feedback=dict(feedback),
            wrist_target_deg=wrist_target_deg,
            captured_monotonic_s=now_s,
        )

    def apply_event(
        self,
        event: SessionEvent,
        *,
        now_s: float,
        feedback: dict[str, float],
        feedback_monotonic_s: float,
        position_command: dict[str, float],
        wrist_target_deg: float,
    ) -> SessionUpdate:
        if event is SessionEvent.STOP:
            if self.state in (SessionState.CLOSED, SessionState.FAULT):
                raise InvalidTransition(f"{event.value} is invalid from {self.state.value}")
            previous = self.state
            self.state = SessionState.CLOSED
            self.control_result = "operator_stop"
            self._record_event(event, now_s=now_s, previous_state=previous)
            return SessionUpdate(state=self.state, close_control=True)
        if event is SessionEvent.EXIT:
            if self.state is not SessionState.READY_TO_EXIT:
                raise InvalidTransition(f"{event.value} is invalid from {self.state.value}")
            previous = self.state
            self.state = SessionState.CLOSED
            self.control_result = "completed"
            self._record_event(event, now_s=now_s, previous_state=previous)
            return SessionUpdate(state=self.state, close_control=True)
        if event is SessionEvent.PLACEMENT_COMPLETE:
            if self.state is not SessionState.PLACING:
                raise InvalidTransition(f"{event.value} is invalid from {self.state.value}")
            self.hold_target = self._capture_hold_target(
                now_s=now_s,
                feedback=feedback,
                feedback_monotonic_s=feedback_monotonic_s,
                position_command=position_command,
                wrist_target_deg=wrist_target_deg,
            )
            previous = self.state
            self.state = SessionState.READY_TO_EXIT
            self._record_event(event, now_s=now_s, previous_state=previous)
            return SessionUpdate(state=self.state, hold_target=self.hold_target)
        if event is SessionEvent.BEGIN_PLACING:
            if self.state is not SessionState.HOLDING:
                raise InvalidTransition(f"{event.value} is invalid from {self.state.value}")
            previous = self.state
            self.state = SessionState.PLACING
            self._record_event(event, now_s=now_s, previous_state=previous)
            return SessionUpdate(state=self.state, rebase_follow=True)
        if (
            event is not SessionEvent.END_RECORDING_AND_HOLD
            or self.state is not SessionState.RECORDING
        ):
            raise InvalidTransition(f"{event.value} is invalid from {self.state.value}")
        self.hold_target = self._capture_hold_target(
            now_s=now_s,
            feedback=feedback,
            feedback_monotonic_s=feedback_monotonic_s,
            position_command=position_command,
            wrist_target_deg=wrist_target_deg,
        )
        previous = self.state
        self.state = SessionState.HOLDING
        self._record_event(event, now_s=now_s, previous_state=previous)
        return SessionUpdate(
            state=self.state,
            freeze_recording=True,
            hold_target=self.hold_target,
        )


class ControlCycleCoordinator:
    """Apply one real control cycle while enforcing the recording boundary."""

    def __init__(
        self,
        session: GraspHoldSession,
        writer: ControlWriter,
        recorder: RecordingSink | None,
    ) -> None:
        self.session = session
        self.writer = writer
        self.recorder = recorder

    def apply_event(
        self,
        event: SessionEvent,
        *,
        boundary: dict[str, object] | None = None,
        now_s: float,
        feedback: dict[str, float],
        feedback_monotonic_s: float,
        position_command: dict[str, float],
        wrist_target_deg: float,
    ) -> SessionUpdate:
        update = self.session.apply_event(
            event,
            now_s=now_s,
            feedback=feedback,
            feedback_monotonic_s=feedback_monotonic_s,
            position_command=position_command,
            wrist_target_deg=wrist_target_deg,
        )
        if update.freeze_recording:
            if self.recorder is None:
                self.session.fail("recording boundary requested without a recorder", now_s=now_s)
            try:
                self.recorder.freeze_recording(**(boundary or {}))
            except Exception as exc:
                self.session.fail(f"recording boundary failed: {exc}", now_s=now_s)
        return update

    def execute_cycle(
        self,
        *,
        now_s: float,
        feedback_monotonic_s: float,
        feedback: dict[str, float],
        temperature_c: float,
        status_raw: int,
        position_command: dict[str, float],
        wrist_velocity_raw: int,
        record_frame: dict[str, object] | None,
    ) -> None:
        self.session.check_feedback(
            now_s=now_s,
            feedback_monotonic_s=feedback_monotonic_s,
            feedback=feedback,
            temperature_c=temperature_c,
            status_raw=status_raw,
        )
        try:
            self.writer.write_position(position_command)
            self.writer.write_wrist_velocity(wrist_velocity_raw)
            if (
                self.session.state is SessionState.RECORDING
                and self.recorder is not None
                and record_frame is not None
            ):
                self.recorder.add_control_frame(**record_frame)
        except Exception as exc:
            self.session.fail(f"control cycle failed: {exc}", now_s=now_s)
