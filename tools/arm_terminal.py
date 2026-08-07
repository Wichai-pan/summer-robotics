#!/usr/bin/env python3
"""Conservative terminal teleoperation for one SO-100/SO-101 follower arm.

This controller is intended for an SSH terminal. Unlike arm_keyboard.py, it
never moves to zero and never starts a calibration flow. It uses the current
joint readings as its initial target and constrains this session to small
offsets around that starting pose.
"""

from __future__ import annotations

import argparse
import select
import sys
import time
from collections.abc import Mapping

from portutil import BOARDS, PortResolutionError, resolve_port


JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)

KEYS = {
    "q": ("shoulder_pan", -1), "a": ("shoulder_pan", 1),
    "w": ("shoulder_lift", -1), "s": ("shoulder_lift", 1),
    "e": ("elbow_flex", -1), "d": ("elbow_flex", 1),
    "r": ("wrist_flex", -1), "f": ("wrist_flex", 1),
    "t": ("wrist_roll", -1), "g": ("wrist_roll", 1),
    "y": ("gripper", -1), "h": ("gripper", 1),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=sorted(BOARDS), help="arm/controller board to control")
    parser.add_argument("--port", help="override automatically resolved serial port")
    parser.add_argument("--step-deg", type=float, default=1.0, help="arm-joint increment per key press")
    parser.add_argument("--gripper-step-deg", type=float, default=3.0, help="gripper increment per key press")
    parser.add_argument(
        "--max-joint-offset-deg", type=float, default=8.0,
        help="maximum arm-joint offset from the startup pose",
    )
    parser.add_argument(
        "--max-gripper-offset-deg", type=float, default=20.0,
        help="maximum gripper offset from the startup pose",
    )
    parser.add_argument("--kp", type=float, default=0.25, help="proportional gain (0, 1]")
    parser.add_argument("--control-hz", type=float, default=20.0, help="command frequency")
    parser.add_argument("--dry-run", action="store_true", help="show controls without opening a serial port")
    return parser.parse_args()


def print_controls() -> None:
    print("\nTerminal controls (one key at a time; no Enter):")
    print("  q/a pan     w/s shoulder lift     e/d elbow")
    print("  r/f wrist flex     t/g wrist roll     y/h gripper")
    print("  p print current pose/target     space hold current pose")
    print("  Esc or Ctrl+C stop and disconnect")


def validate_args(args: argparse.Namespace) -> None:
    if args.step_deg <= 0 or args.gripper_step_deg <= 0:
        raise SystemExit("Step sizes must be positive.")
    if args.max_joint_offset_deg <= 0 or args.max_gripper_offset_deg <= 0:
        raise SystemExit("Maximum offsets must be positive.")
    if not 0 < args.kp <= 1:
        raise SystemExit("--kp must be in (0, 1].")
    if args.control_hz <= 0:
        raise SystemExit("--control-hz must be positive.")


def read_pose(robot) -> dict[str, float]:
    observation: Mapping[str, object] = robot.get_observation()
    pose: dict[str, float] = {}
    for joint in JOINTS:
        key = f"{joint}.pos"
        if key not in observation:
            raise RuntimeError(f"Robot observation has no {key}; available={sorted(observation)}")
        value = observation[key]
        pose[joint] = float(value.item() if hasattr(value, "item") else value)
    return pose


def print_pose(label: str, pose: Mapping[str, float]) -> None:
    formatted = ", ".join(f"{joint}={pose[joint]:.1f}" for joint in JOINTS)
    print(f"{label}: {formatted}")


class RawTerminal:
    def __enter__(self):
        try:
            import termios
            import tty
        except ImportError as exc:
            raise RuntimeError("Terminal key control requires a POSIX/Linux terminal.") from exc
        if not sys.stdin.isatty():
            raise RuntimeError("A real interactive TTY is required; run through ssh -t.")
        self.fd = sys.stdin.fileno()
        self.termios = termios
        self.settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def read_key(self) -> str | None:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        return sys.stdin.read(1) if ready else None

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.settings)


def clamp_target(
    joint: str, proposed: float, startup: Mapping[str, float], args: argparse.Namespace
) -> float:
    maximum = args.max_gripper_offset_deg if joint == "gripper" else args.max_joint_offset_deg
    return max(startup[joint] - maximum, min(startup[joint] + maximum, proposed))


def main() -> int:
    args = parse_args()
    validate_args(args)
    print_controls()
    if args.dry_run:
        print("Dry run complete: no serial port was opened and no motor command was sent.")
        return 0

    try:
        port = resolve_port(BOARDS[args.arm], override=args.port)
    except PortResolutionError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"\nSelected {args.arm} arm on {port}.")
    if input("Verify the arm is clear and 12V can be cut immediately. Type ARM to connect: ").strip() != "ARM":
        print("Cancelled before opening the motor port.")
        return 0

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    robot = SO100Follower(SO100FollowerConfig(port=port, id=f"{args.arm}_arm"))
    connected = False
    try:
        robot.connect(calibrate=False)
        connected = True
        startup = read_pose(robot)
        target = startup.copy()
        print_pose("Startup pose", startup)
        if input("No automatic zero move will occur. Type ENABLE to accept live motor control: ").strip() != "ENABLE":
            print("Cancelled before any motor command.")
            return 0

        period = 1.0 / args.control_hz
        print("Live control enabled. The target is limited to the startup pose plus/minus the configured offsets.")
        with RawTerminal() as terminal:
            while True:
                started = time.monotonic()
                key = terminal.read_key()
                if key in ("\x1b", "\x03"):
                    print("\nStop key received.")
                    break
                if key == "p":
                    print_pose("Measured", read_pose(robot))
                    print_pose("Target", target)
                elif key == " ":
                    target = read_pose(robot)
                    print_pose("Holding current pose", target)
                elif key in KEYS:
                    joint, direction = KEYS[key]
                    step = args.gripper_step_deg if joint == "gripper" else args.step_deg
                    proposed = target[joint] + direction * step
                    target[joint] = clamp_target(joint, proposed, startup, args)
                    print(f"Target {joint}: {target[joint]:.1f}")

                measured = read_pose(robot)
                command = {
                    f"{joint}.pos": measured[joint] + args.kp * (target[joint] - measured[joint])
                    for joint in JOINTS
                }
                robot.send_action(command)
                remaining = period - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
    except KeyboardInterrupt:
        print("\nInterrupted by operator.")
    finally:
        if connected and robot.is_connected:
            robot.disconnect()
            print("Disconnected. Confirm on site whether your motor firmware releases torque after disconnect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
