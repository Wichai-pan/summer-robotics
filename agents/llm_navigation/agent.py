#!/usr/bin/env python3
"""Safe first-stage visual LLM navigation test for XLeRobot.

This script uses RoboCrew's LLMAgent and a live OpenCV camera frame, but its
movement tools are deliberately dry-run tools: they log what Gemini requested
and never open a serial port or command a motor.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_TASK = "Describe the scene and choose at most one safe navigation action."
REQUESTED_ACTIONS: list[str] = []


def configure_robocrew_memory_path() -> None:
    """Work around RoboCrew 0.3.1 creating its SQLite DB inside site-packages.

    RoboCrew imports its memory module even when ``use_memory=False``. Its
    default location is read-only in this Conda installation, so redirect its
    local-only database before importing ``LLMAgent``.
    """
    from robocrew.core.memory import Memory

    runtime_dir = SCRIPT_DIR / "runtime"

    def local_memory_init(self: object, db_filename: str = "robot_memory.db") -> None:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = runtime_dir / db_filename
        self.init_db()

    Memory.__init__ = local_memory_init


configure_robocrew_memory_path()
from robocrew.core.LLMAgent import LLMAgent  # noqa: E402
from robocrew.core.camera import RobotCamera  # noqa: E402

SYSTEM_PROMPT = """
You are the first, safety-constrained navigation layer of XLeRobot.
You receive a single forward-facing RGB camera image.

Your available tools are dry-run simulations. They DO NOT move hardware, but
you must nevertheless plan as if the robot were real.

Rules:
- First describe briefly what you can actually see; do not invent objects.
- If the view is unclear, blocked, or you are uncertain, call report_no_action.
- Never issue more than one movement tool call in one turn.
- Never command more than 0.20 m translation or 20 degrees rotation.
- ``move_forward_one_second`` is only a dry-run representation of the already
  verified keyboard-W motion. Use it only when the human operator explicitly
  confirms that this short path is clear and no person is in it.
- Do not call a movement tool when a person, pet, stair edge, loose cable, or
  obstacle may be in the travel path.
- Prefer report_no_action unless the requested action is clearly safe.
"""


def parse_camera(value: str) -> int | str:
    """Accept a macOS OpenCV index (e.g. 0) or a Linux /dev/video path."""
    return int(value) if value.isdigit() else value


@tool
def move_forward(distance_meters: float) -> str:
    """Dry run only: simulate driving straight forward or backward.

    Positive values mean forward; negative values mean backward. Use at most
    0.20 meters per request and only with a visibly clear path.
    """
    distance = max(-0.20, min(0.20, float(distance_meters)))
    direction = "forward" if distance >= 0 else "backward"
    message = f"DRY RUN — would move {direction} {abs(distance):.2f} m; no motor command sent."
    print(message)
    return message


@tool
def move_forward_one_second() -> str:
    """Dry run only: simulate one second of straight forward motion.

    Use only if the human operator explicitly confirmed that the short path is
    clear. This maps to the separate base_forward_1s.py ground test; it does
    not send a motor command from this LLM script.
    """
    REQUESTED_ACTIONS.append("forward_one_second")
    message = "DRY RUN — would use keyboard-W forward mapping for 1.0 s; no motor command sent."
    print(message)
    return message


@tool
def turn_left(angle_degrees: float) -> str:
    """Dry run only: simulate a left turn, limited to 20 degrees."""
    angle = max(0.0, min(20.0, float(angle_degrees)))
    message = f"DRY RUN — would turn left {angle:.0f}°; no motor command sent."
    print(message)
    return message


@tool
def turn_right(angle_degrees: float) -> str:
    """Dry run only: simulate a right turn, limited to 20 degrees."""
    angle = max(0.0, min(20.0, float(angle_degrees)))
    message = f"DRY RUN — would turn right {angle:.0f}°; no motor command sent."
    print(message)
    return message


@tool
def report_no_action(reason: str) -> str:
    """Report that no movement is safe or necessary, giving a short reason."""
    message = f"NO ACTION — {reason}"
    print(message)
    return message


def require_api_key() -> None:
    load_dotenv(SCRIPT_DIR / ".env")
    # ``GEMINI_API_KEY`` is a common local name. Google / RoboCrew expects the
    # standardized ``GOOGLE_API_KEY`` name, so support both without duplicating
    # a secret in the .env file.
    if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    if not os.getenv("GOOGLE_API_KEY"):
        example = SCRIPT_DIR / ".env.example"
        raise SystemExit(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is not set. Copy "
            f"{example} to {SCRIPT_DIR / '.env'} and fill in the key."
        )


def execute_supervised_forward() -> None:
    """Require two explicit human confirmations before the tested 1 s motion."""
    if "forward_one_second" not in REQUESTED_ACTIONS:
        print("Gemini did not request one-second forward motion; no hardware command will be sent.")
        return

    print("\nGemini requested exactly one forward step using the verified keyboard-W mapping.")
    print("Check the path again: no person, pet, cable, stair edge, or obstacle in the 1-second path.")
    confirmation = input("Type MOVE to permit this one physical step; any other input cancels: ").strip()
    if confirmation != "MOVE":
        print("Physical step cancelled. No motor command sent.")
        return

    print("Launching the independently tested base-forward script. It will require MOVE once more.")
    subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "base_forward_1s.py")], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera",
        default="2",
        help="OpenCV camera index (default: head RGB camera 2 on this Mac), or Linux path such as /dev/camera_center.",
    )
    parser.add_argument("--task", default=DEFAULT_TASK, help="One-shot task for Gemini.")
    parser.add_argument(
        "--supervised-forward",
        action="store_true",
        help="After Gemini requests exactly one forward-second step, require two human MOVE confirmations before executing it.",
    )
    args = parser.parse_args()

    require_api_key()
    camera_source = parse_camera(args.camera)
    camera = RobotCamera(camera_source)
    if not camera.capture.isOpened():
        camera.release()
        raise SystemExit(f"Cannot open camera {camera_source!r}. Run tools/preview_cameras.py first.")

    agent = LLMAgent(
        model="google_genai:gemini-3-flash-preview",
        tools=[move_forward, move_forward_one_second, turn_left, turn_right, report_no_action],
        main_camera=camera,
        name="xlerobot-safe-visual-navigation",
        system_prompt=SYSTEM_PROMPT,
        camera_fov=90,
        thinking_level="low",
        history_len=1,
    )
    REQUESTED_ACTIONS.clear()
    agent.task = args.task

    print("Safe LLM navigation test. Camera is live; all actions are DRY RUN only.")
    try:
        agent.main_loop_content()
    finally:
        camera.release()
        agent.cleanup()
    if args.supervised_forward:
        execute_supervised_forward()
    return 0


if __name__ == "__main__":
    sys.exit(main())
