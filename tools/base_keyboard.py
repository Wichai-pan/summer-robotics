#!/usr/bin/env python3
"""Keyboard control for the three-wheel omnidirectional XLeRobot base.

W/S move forward/back, A/D strafe left/right, Q/E rotate left/right,
Space stops, and X/Escape exits. Use ``--terminal`` over SSH. Terminal mode
has no key-release events, so each movement key expires unless repeated.
"""

from __future__ import annotations

import argparse
import math
import os
import select
import signal
import sys
import time
from typing import Protocol

try:
    from .portutil import BOARDS, PortResolutionError, resolve_port
except ImportError:
    from portutil import BOARDS, PortResolutionError, resolve_port


WHITE_SERIAL = BOARDS["white"]
WHEEL_IDS = [7, 8, 9]
XY_SPEED = 0.12
THETA_SPEED = 40.0
LOOP_HZ = 30

OP_MODE, TORQUE, GOAL_VEL, LOCK = 33, 40, 46, 55
MODE_VELOCITY = 1
SIGN_BIT = 15
MOVEMENT_KEYS = frozenset("wasdqe")


def encode_sm(value: float) -> int:
    """Encode a signed-magnitude servo velocity with sign bit 15."""
    magnitude = min(abs(int(value)), (1 << SIGN_BIT) - 1)
    return ((1 << SIGN_BIT) | magnitude) if value < 0 else magnitude


def body_to_wheel_raw(
    x: float,
    y: float,
    theta: float,
    wheel_radius: float = 0.05,
    base_radius: float = 0.125,
    max_raw: int = 3000,
) -> list[int]:
    """Convert body velocity in m/s and deg/s to three raw wheel velocities."""
    theta_radians = math.radians(theta)
    wheel_angles = [math.radians(angle - 90) for angle in (240, 0, 120)]
    degrees_per_second = [
        math.degrees(
            (math.cos(angle) * x + math.sin(angle) * y + base_radius * theta_radians)
            / wheel_radius
        )
        for angle in wheel_angles
    ]
    steps_per_degree = 4096.0 / 360.0
    raw_magnitudes = [abs(value) * steps_per_degree for value in degrees_per_second]
    maximum = max(raw_magnitudes) if raw_magnitudes else 0.0
    if maximum > max_raw:
        degrees_per_second = [
            value * (max_raw / maximum) for value in degrees_per_second
        ]
    return [int(round(value * steps_per_degree)) for value in degrees_per_second]


def command_from_keys(
    pressed: set[str],
    xy_speed: float = XY_SPEED,
    theta_speed: float = THETA_SPEED,
) -> tuple[float, float, float]:
    """Map the established WASD/QE convention to body velocity."""
    if "space" in pressed:
        return 0.0, 0.0, 0.0
    x = (xy_speed if "w" in pressed else 0.0) - (xy_speed if "s" in pressed else 0.0)
    y = (xy_speed if "a" in pressed else 0.0) - (xy_speed if "d" in pressed else 0.0)
    theta = (theta_speed if "q" in pressed else 0.0) - (
        theta_speed if "e" in pressed else 0.0
    )
    return x, y, theta


def require_servo_success(
    operation: str,
    motor_id: int,
    communication: int,
    packet_error: int,
    communication_success: int,
) -> None:
    """Raise when the servo SDK reports a transport or device error."""
    if communication != communication_success or packet_error != 0:
        raise RuntimeError(
            f"{operation} failed for motor {motor_id}: "
            f"communication={communication}, packet_error={packet_error}"
        )


def write_wheel_velocities(
    group_sync_write: object,
    port_handler: object,
    encoded_velocities: list[int],
    communication_success: int,
) -> None:
    """Send all three wheel commands in one broadcast packet.

    This avoids requesting 90 status replies/second from the shared white-board
    bus. Wheel availability is verified by pings before torque is enabled.
    """
    if len(encoded_velocities) != len(WHEEL_IDS):
        raise ValueError("wheel velocity count does not match wheel IDs")
    group_sync_write.clearParam()
    for motor_id, value in zip(WHEEL_IDS, encoded_velocities):
        if not group_sync_write.addParam(motor_id, [value & 0xFF, (value >> 8) & 0xFF]):
            raise RuntimeError(f"could not add wheel ID {motor_id} to velocity broadcast")
    communication = group_sync_write.txPacket()
    if communication == communication_success:
        return
    require_servo_success(
        "broadcast wheel velocity",
        WHEEL_IDS[0],
        communication,
        0,
        communication_success,
    )


def shutdown_hardware(
    input_backend: KeyInput,
    input_connected: bool,
    packet: object,
    port_handler: object,
    communication_success: int,
) -> list[str]:
    """Attempt every shutdown action and return any failures."""
    errors: list[str] = []
    if input_connected:
        try:
            input_backend.disconnect()
        except Exception as exc:
            errors.append(f"input disconnect failed: {exc}")

    for motor_id in WHEEL_IDS:
        try:
            communication = packet.write2ByteTxOnly(
                port_handler, motor_id, GOAL_VEL, 0
            )
            require_servo_success(
                "zero velocity",
                motor_id,
                communication,
                0,
                communication_success,
            )
        except Exception as exc:
            errors.append(str(exc))
        try:
            communication = packet.write1ByteTxOnly(
                port_handler, motor_id, TORQUE, 0
            )
            require_servo_success(
                "disable torque",
                motor_id,
                communication,
                0,
                communication_success,
            )
        except Exception as exc:
            errors.append(str(exc))

    try:
        port_handler.closePort()
    except Exception as exc:
        errors.append(f"serial close failed: {exc}")
    return errors


class KeyInput(Protocol):
    def connect(self) -> None: ...

    def pressed(self) -> set[str]: ...

    def should_exit(self) -> bool: ...

    def disconnect(self) -> None: ...


class TerminalInput:
    """One-key SSH input with an automatic stop when key repeats cease."""

    def __init__(self, deadman_s: float = 0.25):
        self.deadman_s = deadman_s
        self.active_key: str | None = None
        self.active_until = 0.0
        self.exit_requested = False
        self.fd: int | None = None
        self.saved_attributes = None
        self.termios = None

    def connect(self) -> None:
        try:
            import termios
            import tty
        except ImportError as exc:
            raise RuntimeError("--terminal requires a POSIX terminal") from exc
        if not sys.stdin.isatty():
            raise RuntimeError(
                "stdin is not a TTY; use jetson_robot_exec.sh --interactive"
            )
        self.fd = sys.stdin.fileno()
        self.termios = termios
        self.saved_attributes = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)

    def feed(self, key: str, now: float) -> None:
        key = key.lower()
        if key in {"x", "\x1b"}:
            self.exit_requested = True
            self.active_key = None
        elif key == " ":
            self.active_key = None
            self.active_until = now
        elif key in MOVEMENT_KEYS:
            self.active_key = key
            self.active_until = now + self.deadman_s

    def pressed_at(self, now: float) -> set[str]:
        if self.active_key is None or now > self.active_until:
            self.active_key = None
            return set()
        return {self.active_key}

    def pressed(self) -> set[str]:
        now = time.monotonic()
        if self.fd is not None:
            while select.select([self.fd], [], [], 0)[0]:
                key = os.read(self.fd, 1).decode("utf-8", errors="ignore")
                if key:
                    self.feed(key, now)
        return self.pressed_at(now)

    def should_exit(self) -> bool:
        return self.exit_requested

    def disconnect(self) -> None:
        if self.fd is not None and self.saved_attributes is not None and self.termios is not None:
            self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.saved_attributes)
        self.fd = None


class PynputInput:
    """Original local-desktop key-hold backend, imported only when requested."""

    def __init__(self):
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise RuntimeError("pynput is unavailable; use --terminal over SSH") from exc
        self.keyboard = keyboard
        self.keys: set[str] = set()
        self.exit_requested = False
        self.listener = None

    def connect(self) -> None:
        def on_press(key: object) -> None:
            try:
                self.keys.add(key.char.lower())
            except AttributeError:
                if key == self.keyboard.Key.esc:
                    self.exit_requested = True
                elif key == self.keyboard.Key.space:
                    self.keys.add("space")

        def on_release(key: object) -> None:
            try:
                self.keys.discard(key.char.lower())
            except AttributeError:
                if key == self.keyboard.Key.space:
                    self.keys.discard("space")

        self.listener = self.keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def pressed(self) -> set[str]:
        if "x" in self.keys:
            self.exit_requested = True
        return set(self.keys)

    def should_exit(self) -> bool:
        return self.exit_requested

    def disconnect(self) -> None:
        if self.listener is not None:
            self.listener.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", help="optional white-board serial-port override")
    parser.add_argument("--terminal", action="store_true", help="read keys from an SSH/POSIX TTY")
    parser.add_argument(
        "--deadman-ms",
        type=float,
        default=250.0,
        help="terminal movement stops unless the key repeats within this interval",
    )
    parser.add_argument(
        "--xy-speed-mps",
        type=float,
        default=XY_SPEED,
        help="forward/lateral speed in m/s (default: %(default)s)",
    )
    parser.add_argument(
        "--theta-speed-deg-s",
        type=float,
        default=THETA_SPEED,
        help="yaw speed in deg/s (default: %(default)s)",
    )
    parser.add_argument(
        "--max-runtime-s",
        type=float,
        help="automatically stop and exit after this many seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print key mappings and wheel commands without importing serial or opening hardware",
    )
    return parser.parse_args()


def dry_run(xy_speed: float = XY_SPEED, theta_speed: float = THETA_SPEED) -> int:
    for key in "wasdqe":
        command = command_from_keys({key}, xy_speed, theta_speed)
        print(f"{key.upper()}: body={command} wheels={body_to_wheel_raw(*command)}")
    print("SPACE: stop; X/ESC: stop and exit")
    return 0


def main() -> int:
    args = parse_args()
    if args.deadman_ms <= 0:
        raise SystemExit("--deadman-ms must be positive")
    if args.xy_speed_mps <= 0 or args.theta_speed_deg_s <= 0:
        raise SystemExit("--xy-speed-mps and --theta-speed-deg-s must be positive")
    if args.max_runtime_s is not None and args.max_runtime_s <= 0:
        raise SystemExit("--max-runtime-s must be positive")
    if args.dry_run:
        return dry_run(args.xy_speed_mps, args.theta_speed_deg_s)

    input_backend: KeyInput
    if args.terminal:
        input_backend = TerminalInput(args.deadman_ms / 1000.0)
        if not sys.stdin.isatty():
            raise SystemExit("--terminal requires jetson_robot_exec.sh --interactive")
    else:
        input_backend = PynputInput()

    try:
        from scservo_sdk import COMM_SUCCESS, GroupSyncWrite, PacketHandler, PortHandler
    except ImportError as exc:
        raise SystemExit("scservo_sdk is required for live base control") from exc

    override = args.port or os.environ.get("XLEROBOT_PORT")
    try:
        port = resolve_port(WHITE_SERIAL, override=override)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"White board/base port: {port}")
    port_handler = PortHandler(port)
    if not port_handler.openPort():
        raise SystemExit("cannot open the white-board serial port")
    if not port_handler.setBaudRate(1_000_000):
        port_handler.closePort()
        raise SystemExit("cannot set the white-board serial baud rate")
    packet = PacketHandler(0)
    input_connected = False
    result = 1
    shutdown_errors: list[str] = []
    termination_signal: int | None = None
    previous_signal_handlers: dict[int, object] = {}

    def request_shutdown(signum: int, _frame: object) -> None:
        nonlocal termination_signal
        termination_signal = signum

    try:
        missing = []
        for motor_id in WHEEL_IDS:
            _, communication, packet_error = packet.ping(port_handler, motor_id)
            if communication != COMM_SUCCESS or packet_error != 0:
                missing.append(motor_id)
        if missing:
            raise RuntimeError(f"base motor IDs did not respond: {missing}")

        answer = input(
            "Base is still torque-free. Confirm the area is clear and enter BASE (then wait for W/S controls): "
        ).strip()
        if answer != "BASE":
            print("Cancelled; wheel torque was not enabled.")
            result = 2
        else:
            input_backend.connect()
            input_connected = True

            managed_signals = [signal.SIGINT, signal.SIGTERM]
            if hasattr(signal, "SIGHUP"):
                managed_signals.append(signal.SIGHUP)
            for managed_signal in managed_signals:
                previous_signal_handlers[managed_signal] = signal.signal(
                    managed_signal, request_shutdown
                )

            for motor_id in WHEEL_IDS:
                mode, communication, packet_error = packet.read1ByteTxRx(
                    port_handler, motor_id, OP_MODE
                )
                require_servo_success(
                    "read operating mode",
                    motor_id,
                    communication,
                    packet_error,
                    COMM_SUCCESS,
                )
                if mode != MODE_VELOCITY:
                    for address, value, operation in (
                        (LOCK, 0, "unlock operating mode"),
                        (OP_MODE, MODE_VELOCITY, "set velocity mode"),
                        (LOCK, 1, "lock operating mode"),
                    ):
                        communication, packet_error = packet.write1ByteTxRx(
                            port_handler, motor_id, address, value
                        )
                        require_servo_success(
                            operation,
                            motor_id,
                            communication,
                            packet_error,
                            COMM_SUCCESS,
                        )
                communication, packet_error = packet.write1ByteTxRx(
                    port_handler, motor_id, TORQUE, 1
                )
                require_servo_success(
                    "enable torque",
                    motor_id,
                    communication,
                    packet_error,
                    COMM_SUCCESS,
                )

            print(
                "W/S forward/back, A/D strafe, Q/E rotate, Space stop, X/Esc exit. "
                + (
                    f"Terminal dead-man: {args.deadman_ms:.0f} ms."
                    if args.terminal
                    else ""
                )
            )
            wheel_velocity_writer = GroupSyncWrite(port_handler, packet, GOAL_VEL, 2)
            period = 1.0 / LOOP_HZ
            started = time.monotonic()
            while termination_signal is None and not input_backend.should_exit():
                if args.max_runtime_s is not None and time.monotonic() - started >= args.max_runtime_s:
                    print("Base session time limit reached; stopping.")
                    break
                x, y, theta = command_from_keys(
                    input_backend.pressed(),
                    args.xy_speed_mps,
                    args.theta_speed_deg_s,
                )
                raw = body_to_wheel_raw(x, y, theta)
                write_wheel_velocities(
                    wheel_velocity_writer,
                    port_handler,
                    [encode_sm(velocity) for velocity in raw],
                    COMM_SUCCESS,
                )
                time.sleep(period)
            result = 128 + termination_signal if termination_signal is not None else 0
    finally:
        shutdown_errors = shutdown_hardware(
            input_backend,
            input_connected,
            packet,
            port_handler,
            COMM_SUCCESS,
        )
        if shutdown_errors:
            print("WARNING: base shutdown was incomplete:", file=sys.stderr)
            for error in shutdown_errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print("Base stopped, wheel torque disabled, serial port closed.")
        for managed_signal, previous_handler in previous_signal_handlers.items():
            signal.signal(managed_signal, previous_handler)

    return 1 if shutdown_errors else result


if __name__ == "__main__":
    raise SystemExit(main())
