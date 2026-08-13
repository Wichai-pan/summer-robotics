import sys
import signal
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
    prepare_wheels_stopped,
    shutdown_hardware,
    write_wheel_velocities,
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


def test_wheel_velocity_uses_one_broadcast_for_all_three_wheels() -> None:
    added: list[tuple[int, list[int]]] = []

    class GroupWriter:
        def clearParam(self) -> None:
            pass

        def addParam(self, motor_id: int, data: list[int]) -> bool:
            added.append((motor_id, data))
            return True

        def txPacket(self) -> int:
            return 0

    write_wheel_velocities(GroupWriter(), [1, 0x8002, 3], 0)
    assert added == [(7, [1, 0]), (8, [2, 128]), (9, [3, 0])]


def test_preflight_broadcasts_zero_before_any_wheel_torque_enable() -> None:
    events: list[tuple[str, int]] = []

    class Packet:
        def read1ByteTxRx(self, _port: object, _motor_id: int, _address: int):
            return base_keyboard.MODE_VELOCITY, 0, 0

        def write1ByteTxRx(self, _port: object, motor_id: int, address: int, _value: int):
            if address == base_keyboard.TORQUE:
                events.append(("torque", motor_id))
            return 0, 0

    class GroupWriter:
        def __init__(self, *_args: object):
            pass

        def clearParam(self) -> None:
            pass

        def addParam(self, _motor_id: int, _data: list[int]) -> bool:
            return True

        def txPacket(self) -> int:
            events.append(("zero", 0))
            return 0

    prepare_wheels_stopped(Packet(), object(), 0, GroupWriter)
    assert events == [("zero", 0), ("torque", 7), ("torque", 8), ("torque", 9)]


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
        GroupSyncWrite=lambda *_args: object(),
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
        def write2ByteTxOnly(
            self, _port: object, motor_id: int, _address: int, _value: int
        ) -> int:
            events.append(("zero", motor_id))
            if motor_id == 7:
                raise RuntimeError("zero write failed")
            return 0

        def write1ByteTxOnly(
            self, _port: object, motor_id: int, _address: int, _value: int
        ) -> int:
            events.append(("torque-off", motor_id))
            return 1 if motor_id == 8 else 0

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


def test_sigterm_requests_zero_speed_and_torque_off() -> None:
    writes: list[tuple[int, int, int]] = []
    handlers: dict[int, object] = {}
    signal_calls: list[tuple[int, object]] = []
    term_sent = False

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
            self, _port: FakePort, motor_id: int, address: int, value: int
        ) -> tuple[int, int]:
            writes.append((motor_id, address, value))
            return 0, 0

        def write2ByteTxRx(
            self, _port: FakePort, motor_id: int, address: int, value: int
        ) -> tuple[int, int]:
            nonlocal term_sent
            writes.append((motor_id, address, value))
            if address == base_keyboard.GOAL_VEL and value != 0 and not term_sent:
                term_sent = True
                handler = handlers[signal.SIGTERM]
                assert callable(handler)
                handler(signal.SIGTERM, None)
            return 0, 0

        def write2ByteTxOnly(
            self, _port: FakePort, motor_id: int, address: int, value: int
        ) -> int:
            writes.append((motor_id, address, value))
            return 0

        def write1ByteTxOnly(
            self, _port: FakePort, motor_id: int, address: int, value: int
        ) -> int:
            writes.append((motor_id, address, value))
            return 0

    class FakeGroupWriter:
        def __init__(self, *_args: object):
            pass

        def clearParam(self) -> None:
            pass

        def addParam(self, _motor_id: int, _data: list[int]) -> bool:
            return True

        def txPacket(self) -> int:
            nonlocal term_sent
            if not term_sent:
                term_sent = True
                handler = handlers[signal.SIGTERM]
                assert callable(handler)
                handler(signal.SIGTERM, None)
            return 0

    class FakeInput:
        def connect(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

        def pressed(self) -> set[str]:
            return {"w"}

        def should_exit(self) -> bool:
            return False

    def fake_signal(signum: int, handler: object) -> object:
        previous = handlers.get(signum, f"original-{signum}")
        handlers[signum] = handler
        signal_calls.append((signum, handler))
        return previous

    fake_sdk = SimpleNamespace(
        COMM_SUCCESS=0,
        GroupSyncWrite=FakeGroupWriter,
        PacketHandler=lambda _protocol: FakePacket(),
        PortHandler=lambda _port: FakePort(),
    )
    with (
        patch.object(sys, "argv", ["base_keyboard.py"]),
        patch.dict(sys.modules, {"scservo_sdk": fake_sdk}),
        patch.object(base_keyboard, "PynputInput", lambda: FakeInput()),
        patch.object(base_keyboard, "resolve_port", return_value="fake-port"),
        patch.object(base_keyboard.signal, "signal", side_effect=fake_signal),
        patch.object(base_keyboard.time, "sleep"),
        patch("builtins.input", return_value="BASE"),
    ):
        assert base_keyboard.main() == 128 + signal.SIGTERM

    for motor_id in base_keyboard.WHEEL_IDS:
        assert (motor_id, base_keyboard.GOAL_VEL, 0) in writes
        assert (motor_id, base_keyboard.TORQUE, 0) in writes
    assert len(signal_calls) >= 4
