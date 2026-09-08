#!/usr/bin/env python3
"""Pure state and verification logic for segmented mobile manipulation."""

from __future__ import annotations

from enum import Enum, auto


class State(Enum):
    PREPARE_PICK = auto()
    RECORD_PICK = auto()
    RETRACT_TO_HOLD = auto()
    FINALIZE_PICK = auto()
    HOLD = auto()
    WAIT_FOR_PLACE = auto()
    PREPARE_PLACE = auto()
    RECORD_PLACE = auto()
    VERIFY_PLACE = auto()
    VERIFY_RELEASE = auto()
    RETURN_EMPTY = auto()
    VERIFY_EMPTY = auto()
    FINALIZE_PLACE = auto()
    DONE = auto()
    FAULT = auto()
    ABORTED = auto()


ALLOWED: dict[State, set[State]] = {
    State.PREPARE_PICK: {State.RECORD_PICK, State.DONE, State.FAULT},
    # v is the operator's authoritative grasp-success assertion. No telemetry
    # classifier or second y/n decision exists in this collection workflow.
    State.RECORD_PICK: {State.RETRACT_TO_HOLD, State.DONE, State.FAULT},
    State.RETRACT_TO_HOLD: {State.FINALIZE_PICK, State.DONE, State.FAULT},
    State.FINALIZE_PICK: {State.HOLD, State.FAULT},
    State.HOLD: {State.WAIT_FOR_PLACE, State.DONE, State.FAULT},
    State.WAIT_FOR_PLACE: {State.PREPARE_PLACE, State.DONE, State.FAULT},
    State.PREPARE_PLACE: {State.RECORD_PLACE, State.DONE, State.FAULT},
    State.RECORD_PLACE: {State.VERIFY_PLACE, State.DONE, State.FAULT},
    State.VERIFY_PLACE: {State.RECORD_PLACE, State.VERIFY_RELEASE, State.FAULT},
    State.VERIFY_RELEASE: {State.RECORD_PLACE, State.RETURN_EMPTY, State.FAULT},
    State.RETURN_EMPTY: {State.VERIFY_EMPTY, State.DONE, State.FAULT},
    State.VERIFY_EMPTY: {State.RETURN_EMPTY, State.FINALIZE_PLACE, State.FAULT},
    State.FINALIZE_PLACE: {State.DONE, State.FAULT},
    State.DONE: set(),
    State.FAULT: {State.DONE},
    State.ABORTED: set(),
}

# The operator's global discard command is legal from every live state. This
# is deliberately separate from the task-specific q/h/r/p/o commands.
for _state, _targets in ALLOWED.items():
    if _state not in {State.DONE, State.ABORTED}:
        _targets.add(State.ABORTED)


PICK_RECORDED_STATES = {State.RECORD_PICK, State.RETRACT_TO_HOLD}
PLACE_RECORDED_STATES = {
    State.RECORD_PLACE,
    State.VERIFY_PLACE,
    State.VERIFY_RELEASE,
    State.RETURN_EMPTY,
}


class StateMachine:
    def __init__(self, initial: State) -> None:
        self.state = initial
        self.history = [initial]

    def transition(self, target: State) -> None:
        if target not in ALLOWED[self.state]:
            raise RuntimeError(f"illegal state transition: {self.state.name} -> {target.name}")
        self.state = target
        self.history.append(target)


def pick_frames_enabled(state: State) -> bool:
    return state in PICK_RECORDED_STATES


def place_frames_enabled(state: State) -> bool:
    return state in PLACE_RECORDED_STATES
