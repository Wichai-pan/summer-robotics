import sys
from types import SimpleNamespace
from unittest.mock import patch

import tools.base_keyboard as base_keyboard
from tools.base_keyboard import (
    THETA_SPEED,
    XY_SPEED,
    TerminalInput,
    body_to_wheel_raw,
    command_from_keys,
    encode_sm,
    shutdown_hardware,
)


def test_wasd_qe_mapping_matches_established_base_convention() -> None:
    assert command_from_keys({"w"}) == (XY_SPEED, 0.0, 0.0)
    assert command_from_keys({"s"}) == (-XY_SPEED, 0.0, 0.0)
    assert command_from_keys({"a"}) == (0.0, XY_SPEED, 0.0)
    assert command_from_keys({"d"}) == (0.0, -XY_SPEED, 0.0)
    assert command_from_keys({"q"}) == (0.0, 0.0, THETA_SPEED)
    assert command_from_keys({"e"}) == (0.0, 0.0, -THETA_SPEED)
    assert command_from_keys({"w", "s", "q", "e"}) == (0.0, 0.0, 0.0)
    assert command_from_keys({"w", "space"}) == (0.0, 0.0, 0.0)


def test_terminal_input_stops_after_deadman_timeout() -> None:
    keys = TerminalInput(deadman_s=0.25)
    keys.feed("w", now=10.0)
    assert keys.pressed_at(10.24) == {"w"}
    assert keys.pressed_at(10.26) == set()


def test_terminal_stop_and_exit_are_fail_safe() -> None:
    keys = TerminalInput(deadman_s=0.25)
    keys.feed("a", now=1.0)
    keys.feed(" ", now=1.1)
    assert keys.pressed_at(1.1) == set()
    keys.feed("q", now=2.0)
    keys.feed("\x1b", now=2.1)
    assert keys.should_exit()
    assert keys.pressed_at(2.1) == set()


def test_wheel_conversion_and_signed_encoding_are_bounded() -> None:
    raw = body_to_wheel_raw(XY_SPEED, XY_SPEED, THETA_SPEED)
    assert len(raw) == 3
    assert max(abs(value) for value in raw) <= 3000
    assert encode_sm(-123) == (1 << 15) | 123
    assert encode_sm(123) == 123


def test_input_backend_failure_never_enables_torque() -> None:
    writes: list[tuple[int, int]] = []

    class FakePort:
        def openPort(self) -> bool:
            return True

        def setBaudRate(self, _baud: int) -> bool:
            return True

        def closePort(self) -> None:
            pass

    class FakePacket:
        def ping(self, _port: FakePort, _motor_id: int) -> tuple[int, int, int]:
            return 0, 0, 0

        def read1ByteTxRx(
            self, _port: FakePort, _motor_id: int, _address: int
        ) -> tuple[int, int, int]:
            return base_keyboard.MODE_VELOCITY, 0, 0

        def write1ByteTxRx(
            self, _port: FakePort, _motor_id: int, address: int, value: int
        ) -> tuple[int, int]:
            writes.append((address, value))
            return 0, 0

        def write2ByteTxRx(
            self, _port: FakePort, _motor_id: int, _address: int, _value: int
        ) -> tuple[int, int]:
            return 0, 0

    class FailingInput:
        def connect(self) -> None:
            raise RuntimeError("input unavailable")

        def disconnect(self) -> None:
            pass

    fake_sdk = SimpleNamespace(
        COMM_SUCCESS=0,
        PacketHandler=lambda _protocol: FakePacket(),
        PortHandler=lambda _port: FakePort(),
    )
    with (
        patch.object(sys, "argv", ["base_keyboard.py"]),
        patch.dict(sys.modules, {"scservo_sdk": fake_sdk}),
        patch.object(base_keyboard, "PynputInput", lambda: FailingInput()),
        patch.object(base_keyboard, "resolve_port", return_value="fake-port"),
        patch("builtins.input", return_value="BASE"),
    ):
        try:
            base_keyboard.main()
        except RuntimeError as exc:
            assert str(exc) == "input unavailable"
        else:
            raise AssertionError("input initialization failure did not propagate")

    assert (base_keyboard.TORQUE, 1) not in writes


def test_shutdown_attempts_all_actions_after_individual_failures() -> None:
    events: list[tuple[str, int | None]] = []

    class BrokenInput:
        def disconnect(self) -> None:
            events.append(("disconnect", None))
            raise RuntimeError("terminal restore failed")

    class BrokenPacket:
        def write2ByteTxRx(
            self, _port: object, motor_id: int, _address: int, _value: int
        ) -> tuple[int, int]:
            events.append(("zero", motor_id))
            if motor_id == 7:
                raise RuntimeError("zero write failed")
            return 0, 0

        def write1ByteTxRx(
            self, _port: object, motor_id: int, _address: int, _value: int
        ) -> tuple[int, int]:
            events.append(("torque-off", motor_id))
            return (1, 0) if motor_id == 8 else (0, 0)

    class FakePort:
        def closePort(self) -> None:
            events.append(("close", None))

    errors = shutdown_hardware(BrokenInput(), True, BrokenPacket(), FakePort(), 0)

    assert ("disconnect", None) in events
    assert [("zero", motor_id) for motor_id in base_keyboard.WHEEL_IDS] == [
        event for event in events if event[0] == "zero"
    ]
    assert [("torque-off", motor_id) for motor_id in base_keyboard.WHEEL_IDS] == [
        event for event in events if event[0] == "torque-off"
    ]
    assert events[-1] == ("close", None)
    assert len(errors) == 3
