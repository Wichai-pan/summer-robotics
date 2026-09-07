#!/usr/bin/env python3
"""Exercise the grasp-hold lifecycle without importing or accessing hardware."""

from __future__ import annotations

import json
import sys

from grasp_hold_session import ControlCycleCoordinator, GraspHoldSession, SessionEvent


JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "gripper")


class FakeWriter:
    def __init__(self) -> None:
        self.cycles = 0

    def write_position(self, command: dict[str, float]) -> None:
        self.cycles += 1

    def write_wrist_velocity(self, command_raw: int) -> None:
        pass


class FakeRecorder:
    def __init__(self) -> None:
        self.frames = 0
        self.boundaries = 0

    def add_control_frame(self, **frame: object) -> None:
        self.frames += 1

    def freeze_recording(self, **boundary: object) -> None:
        self.boundaries += 1


def snapshot(now_s: float, value: float = 0.0) -> dict[str, object]:
    values = {joint: value for joint in JOINTS}
    return {
        "now_s": now_s,
        "feedback_monotonic_s": now_s,
        "feedback": values,
        "position_command": values,
        "wrist_target_deg": 0.0,
    }


def cycle_snapshot(now_s: float, value: float = 0.0) -> dict[str, object]:
    event_snapshot = snapshot(now_s, value)
    event_snapshot.pop("wrist_target_deg")
    return event_snapshot


def main() -> int:
    writer = FakeWriter()
    recorder = FakeRecorder()
    session = GraspHoldSession()
    control = ControlCycleCoordinator(session, writer, recorder)
    control.execute_cycle(
        **cycle_snapshot(1.0),
        temperature_c=30.0,
        status_raw=0,
        wrist_velocity_raw=0,
        record_frame={"sample": 1},
    )
    control.apply_event(
        SessionEvent.END_RECORDING_AND_HOLD,
        boundary={"phase": "holding"},
        **snapshot(2.0),
    )
    control.execute_cycle(
        **cycle_snapshot(3.0),
        temperature_c=30.0,
        status_raw=0,
        wrist_velocity_raw=0,
        record_frame={"sample": 2},
    )
    control.apply_event(SessionEvent.BEGIN_PLACING, **snapshot(4.0))
    control.apply_event(SessionEvent.PLACEMENT_COMPLETE, **snapshot(5.0))
    control.apply_event(SessionEvent.EXIT, **snapshot(6.0))

    forbidden = sorted(
        name
        for name in sys.modules
        if name == "lerobot"
        or name.startswith("lerobot.")
        or name in {"cv2", "pyorbbecsdk", "rclpy", "scservo_sdk"}
    )
    result = {
        "status": "PASS" if not forbidden else "FAIL",
        "final_state": session.state.value,
        "frames_before_boundary": recorder.frames,
        "recording_boundaries": recorder.boundaries,
        "control_cycles": writer.cycles,
        "forbidden_imports": forbidden,
        "hardware_access": False,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
