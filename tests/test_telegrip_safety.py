from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest


TELEGRIP_ROOT = Path(__file__).resolve().parents[1] / "external" / "telegrip"
sys.path.insert(0, str(TELEGRIP_ROOT))
pytest.importorskip("torch")
pytest.importorskip("pybullet")

from telegrip.config import JOINT_NAMES, TelegripConfig  # noqa: E402
from telegrip.control_loop import ControlLoop  # noqa: E402
from telegrip.core.robot_interface import (  # noqa: E402
    RobotInterface,
    SafetyViolation,
)


def safety_interface() -> RobotInterface:
    interface = RobotInterface(TelegripConfig())
    interface.joint_limits_min_deg = np.full(6, -180.0)
    interface.joint_limits_max_deg = np.full(6, 180.0)
    interface.session_start_angles["left"] = np.zeros(6)
    interface.last_commanded_angles["left"] = np.zeros(6)
    return interface


def test_session_bounds_and_slew_rate() -> None:
    interface = safety_interface()

    assert interface.config.follower_ids == {
        "left": "black_arm",
        "right": "white_arm_leader_follow",
    }

    bounded = interface.clamp_to_session_bounds(
        "left", np.array([50.0, -50.0, 20.0, 10.0, 8.0, 45.0])
    )
    np.testing.assert_allclose(bounded, [3.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    limited = interface._rate_limited_angles(
        "left", np.array([3.0, -3.0, 3.0, 3.0, 3.0, 45.0]), 0.05
    )
    np.testing.assert_allclose(limited, [0.25, 0.0, 0.0, 0.0, 0.0, 0.0])


def test_tracking_error_raises_safety_violation() -> None:
    interface = safety_interface()

    class MockRobot:
        @staticmethod
        def send_action(action):
            return action

        @staticmethod
        def get_observation():
            return {
                f"{joint}.pos": 30.0 if joint == "shoulder_pan" else 0.0
                for joint in JOINT_NAMES
            }

    with pytest.raises(SafetyViolation, match="tracking error"):
        interface._send_arm_command("left", MockRobot(), np.zeros(6), 0.05)


def test_stale_vr_stream_requests_immediate_torque_off() -> None:
    class MockRobotInterface:
        is_engaged = True

        def __init__(self):
            self.stop_calls = 0

        def emergency_disengage(self):
            self.stop_calls += 1
            self.is_engaged = False

    control = ControlLoop(asyncio.Queue(), TelegripConfig())
    robot = MockRobotInterface()
    control.robot_interface = robot
    control.vr_freshness_check = lambda: False

    control._enforce_vr_freshness()

    assert robot.stop_calls == 1
    assert not robot.is_engaged


def test_torque_free_connect_never_enables_torque() -> None:
    events = []

    class MockBus:
        motors = ["shoulder_pan", "gripper"]
        is_connected = False

        def connect(self):
            self.is_connected = True
            events.append("connect")

        def disable_torque(self, num_retry=0):
            events.append(("disable_torque", num_retry))

        def write(self, register, motor, value):
            events.append(("write", register, motor, value))

    class MockConfig:
        position_p_coefficient = 16
        position_i_coefficient = 0
        position_d_coefficient = 32

    class MockRobot:
        id = "black_arm"
        is_calibrated = True
        bus = MockBus()
        config = MockConfig()

    RobotInterface._connect_torque_free(MockRobot())

    assert events[0] == "connect"
    assert events[1] == ("disable_torque", 3)
    assert events[-1] == ("disable_torque", 3)
    assert not any(event == "enable_torque" for event in events)
