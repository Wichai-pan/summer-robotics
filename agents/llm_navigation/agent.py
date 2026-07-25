#!/usr/bin/env python3
"""Safe first-stage visual LLM navigation test for XLeRobot.

This script uses RoboCrew's LLMAgent and a live OpenCV camera frame, but its
movement tools are deliberately dry-run tools: they log what Gemini requested
and never open a serial port or command a motor.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_TASK = "Describe the scene and choose at most one safe navigation action."
REQUESTED_ACTION: str | None = None
REQUESTED_TARGET_APPROACH: tuple[str, float] | None = None
DEFAULT_DEPTH_PYTHON = Path.home() / "miniconda3" / "envs" / "orbbec-depth" / "bin" / "python"

# These are ordinary COCO object labels that the current YOLO model can emit.
# A person is intentionally excluded: the target-approach path is for an
# inanimate-object demo only, and no physical target approach is enabled here.
APPROACHABLE_TARGETS = frozenset({"bottle", "book", "cell phone", "cup", "keyboard", "remote"})


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

Your tools describe fixed, short base movements. The host program may execute
one requested action only after two explicit human confirmations.

Rules:
- First describe briefly what you can actually see; do not invent objects.
- If the view is unclear, blocked, or you are uncertain, call report_no_action.
- Never issue more than one movement tool call in one turn.
- The only permitted movements are: one second forward, a small left turn, or
  a small right turn. Do not invent distances, durations, or other actions.
- A visible person elsewhere in the image is not by itself proof that the
  first short motion corridor is blocked. If the task says that the operator
  will re-check the corridor before every action, you may propose one small
  action; the host will always require two separate MOVE confirmations before
  any motor command is sent.
- Do not call a movement tool when the image shows a person, pet, stair edge,
  loose cable, or obstacle actually occupying the first short motion corridor,
  or when the task gives no operator-clearance statement.
- Fresh depth telemetry, if supplied in the task, is a geometric measurement
  of the forward center ROI. It is useful evidence about clearance, but is not
  an identity or person-distance detector.
- Prefer report_no_action unless the requested action is clearly safe.
- When the ``request_target_approach`` tool is available, it is a dry-run
  handoff to a *local* YOLO + depth tracker. Use it only for one clearly
  visible inanimate target from its documented labels. It does not control a
  motor, does not follow people, and must not be combined with a movement tool.
"""


def parse_camera(value: str) -> int | str:
    """Accept a macOS OpenCV index (e.g. 0) or a Linux /dev/video path."""
    return int(value) if value.isdigit() else value


def open_live_camera(camera_source: int | str) -> RobotCamera:
    """Open and warm up the RGB stream after a possible SDK depth read."""
    camera = RobotCamera(camera_source)
    if not camera.capture.isOpened():
        camera.release()
        raise SystemExit(f"Cannot open camera {camera_source!r}. Run tools/preview_cameras.py first.")

    # On macOS, Gemini's UVC colour stream can report "opened" immediately
    # after the SDK stops Depth while returning a few empty frames. RoboCrew
    # does not guard against None frames, so establish one real frame first.
    for _ in range(25):
        ok, frame = camera.capture.read()
        if ok and frame is not None:
            return camera
        time.sleep(0.2)
    camera.release()
    raise SystemExit(
        f"Camera {camera_source!r} reopened but produced no frame after a depth read. "
        "Wait a few seconds, then run tools/preview_cameras.py 2 to verify the RGB stream."
    )


def record_action(action: str) -> None:
    global REQUESTED_ACTION
    if REQUESTED_ACTION is None:
        REQUESTED_ACTION = action


def record_target_approach(target_label: str, standoff_m: float) -> None:
    global REQUESTED_TARGET_APPROACH
    if REQUESTED_TARGET_APPROACH is None:
        REQUESTED_TARGET_APPROACH = (target_label, standoff_m)


@tool
def move_forward_one_second() -> str:
    """Dry run only: simulate one second of straight forward motion.

    Use only if the human operator explicitly confirmed that the short path is
    clear. This maps to the separate base_forward_1s.py ground test; it does
    not send a motor command from this LLM script.
    """
    record_action("forward_1s")
    message = "DRY RUN — would use keyboard-W forward mapping for 1.0 s; no motor command sent."
    print(message)
    return message


@tool
def turn_left_small() -> str:
    """Request one small left turn (the tested keyboard-Q mapping, about 16°)."""
    record_action("turn_left_small")
    message = "DRY RUN — would use keyboard-Q left turn mapping for about 16°; no motor command sent."
    print(message)
    return message


@tool
def turn_right_small() -> str:
    """Request one small right turn (the tested keyboard-E mapping, about 16°)."""
    record_action("turn_right_small")
    message = "DRY RUN — would use keyboard-E right turn mapping for about 16°; no motor command sent."
    print(message)
    return message


@tool
def request_target_approach(target_label: str, standoff_m: float = 0.50) -> str:
    """Dry-run only: hand a visible inanimate object to local YOLO RGB-D tracking.

    ``target_label`` must be one of: bottle, book, cell phone, cup, keyboard,
    remote. ``standoff_m`` is the desired object distance in metres and must be
    between 0.20 and 1.00. This never opens a serial port or moves the robot;
    the host only prints the safe local tracker command for a human to run.
    """
    normalized_label = target_label.strip().lower()
    if normalized_label not in APPROACHABLE_TARGETS:
        message = (
            f"DRY RUN rejected — {target_label!r} is not an allowed inanimate target. "
            f"Allowed: {', '.join(sorted(APPROACHABLE_TARGETS))}."
        )
        print(message)
        return message
    if not 0.20 <= standoff_m <= 1.00:
        message = "DRY RUN rejected — standoff_m must be between 0.20 m and 1.00 m."
        print(message)
        return message
    record_target_approach(normalized_label, standoff_m)
    message = (
        f"DRY RUN — would hand target={normalized_label!r}, standoff={standoff_m:.2f} m "
        "to the local YOLO + aligned-depth tracker; no motor command sent."
    )
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


def read_depth_statistics(args: argparse.Namespace) -> dict[str, float | int | None] | None:
    """Read a fresh center-ROI depth sample in the isolated Orbbec environment.

    The main navigation environment intentionally does not install pyorbbecsdk,
    because its AV dependency conflicts with LeRobot. A failed reading is a
    failed-closed condition: forward motion is not offered to the operator.
    """
    depth_python = Path(args.depth_python).expanduser()
    if not depth_python.is_file():
        print(
            "Depth gate blocked forward motion: the Orbbec Python executable was not found at "
            f"{depth_python}. Use --depth-python to set it explicitly."
        )
        return None

    command = [str(depth_python), str(REPO_ROOT / "tools" / "orbbec_depth_probe.py"), "--json", "--samples", str(args.depth_samples)]
    if args.depth_sudo:
        # The operator authenticates visibly with `sudo -v` before starting
        # the agent. Do not hide an interactive password prompt in captured
        # output: a missing/expired ticket must fail closed immediately.
        command = ["sudo", "-n", "-E", *command]
    print("Reading Gemini 335 depth before offering a forward step…")
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=args.depth_timeout_s)
    except subprocess.TimeoutExpired:
        print(f"Depth gate blocked forward motion: depth read timed out after {args.depth_timeout_s} s.")
        return None

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        print("Depth gate blocked forward motion: Gemini depth read failed" + (f" ({detail[-1]})." if detail else "."))
        return None

    # The SDK can print extension-loading diagnostics before our JSON result.
    for line in reversed(result.stdout.splitlines()):
        try:
            statistics = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(statistics, dict) and "roi_p10_m" in statistics:
            return statistics
    print("Depth gate blocked forward motion: no readable depth statistics were returned.")
    return None


class OrbbecSnapshotCamera:
    """RoboCrew camera adapter backed by one SDK-owned RGB-D snapshot.

    This keeps Gemini 335 colour and depth in the same Orbbec SDK pipeline;
    it deliberately never opens OpenCV's UVC stream for the head camera.
    """

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.snapshot_path = SCRIPT_DIR / "runtime" / "latest_orbbec_rgbd.jpg"
        self.metadata_path = SCRIPT_DIR / "runtime" / "latest_orbbec_rgbd.json"
        self._image_bytes: bytes | None = None
        self.latest_statistics: dict[str, float | int | None] | None = None

    def release(self) -> None:
        """Keep the same interface as RoboCrew's RobotCamera."""

    def capture_snapshot(self) -> dict[str, float | int | None] | None:
        # Never let a failed fresh capture fall back to the prior decision's
        # image or depth. Each navigation decision must use a new RGB-D frame.
        self._image_bytes = None
        self.latest_statistics = None
        depth_python = Path(self.args.depth_python).expanduser()
        if not depth_python.is_file():
            print(f"Orbbec SDK camera unavailable: Python was not found at {depth_python}.")
            return None
        command = [
            str(depth_python),
            str(REPO_ROOT / "tools" / "orbbec_rgbd_snapshot.py"),
            "--output",
            str(self.snapshot_path),
            "--metadata",
            str(self.metadata_path),
            "--samples",
            str(self.args.depth_samples),
        ]
        if self.args.depth_sudo:
            # SDK snapshots write metadata to a file, so stdout need not be
            # captured. This keeps any sudo password prompt visible instead
            # of timing out invisibly inside a subprocess pipe.
            command = ["sudo", "-E", *command]
        print("Capturing one Gemini 335 RGB-D snapshot through Orbbec SDK…")
        try:
            result = subprocess.run(command, check=False, timeout=self.args.depth_timeout_s)
        except subprocess.TimeoutExpired:
            print(f"Orbbec SDK snapshot timed out after {self.args.depth_timeout_s} s.")
            return None
        if result.returncode != 0:
            print(f"Orbbec SDK snapshot failed (exit status {result.returncode}).")
            return None
        try:
            statistics = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if not isinstance(statistics, dict) or "roi_p10_m" not in statistics:
                raise ValueError("missing ROI depth statistics")
            self._image_bytes = Path(str(statistics["image_path"])).read_bytes()
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            print(f"Orbbec SDK snapshot produced no readable RGB-D result: {exc}")
            return None
        self.latest_statistics = statistics
        return statistics

    def capture_image(self, camera_fov: float = 90, center_angle: float = 0, navigation_mode: str = "normal") -> bytes:
        # The unused parameters match RobotCamera.capture_image for RoboCrew.
        if self._image_bytes is None and self.capture_snapshot() is None:
            raise RuntimeError("Cannot capture an Orbbec RGB-D snapshot for Gemini.")
        assert self._image_bytes is not None
        image_bytes = self._image_bytes
        self._image_bytes = None
        return image_bytes


def depth_allows_statistics(args: argparse.Namespace, statistics: dict[str, float | int | None] | None) -> bool:
    """Apply the forward no-go threshold to already-read depth statistics."""
    if statistics is None:
        return False
    try:
        near_m = float(statistics["roi_p10_m"])
        median_m = float(statistics["roi_median_m"])
    except (KeyError, TypeError, ValueError):
        print("Depth gate blocked forward motion: invalid ROI near-distance value.")
        return False
    print(
        "Gemini depth: "
        f"center ROI P10={near_m:.3f} m, median={median_m:.3f} m "
        f"({statistics['valid_frames']}/{statistics['requested_samples']} frames)."
    )
    if near_m < args.depth_min_m:
        print(
            f"Depth gate blocked forward motion: {near_m:.3f} m is below the "
            f"{args.depth_min_m:.3f} m no-go limit."
        )
        return False
    return True


def depth_allows_forward(args: argparse.Namespace) -> bool:
    """Require a valid forward-center depth reading above the configured no-go limit."""
    return depth_allows_statistics(args, read_depth_statistics(args))


def depth_context_from_statistics(args: argparse.Namespace, statistics: dict[str, float | int | None] | None) -> str:
    """Collect pre-decision depth context without opening a motor port.

    Gemini sees this before choosing a tool, so a person in the far field is
    not automatically treated as an immediate obstruction. The execution-time
    gate below still takes a fresh sample before it offers MOVE.
    """
    if statistics is None:
        return (
            "Depth telemetry is unavailable. Do not propose forward motion; "
            "a small turn may still be proposed if the operator-clearance statement applies."
        )
    try:
        near_m = float(statistics["roi_p10_m"])
        median_m = float(statistics["roi_median_m"])
    except (KeyError, TypeError, ValueError):
        return "Depth telemetry is malformed. Do not propose forward motion."
    if near_m < args.depth_min_m:
        return (
            f"Fresh depth telemetry: forward center ROI P10 is {near_m:.3f} m, below the "
            f"{args.depth_min_m:.3f} m hard no-go limit. Do not propose forward motion."
        )
    return (
        f"Fresh depth telemetry: forward center ROI P10 is {near_m:.3f} m and median is "
        f"{median_m:.3f} m ({statistics['valid_frames']}/{statistics['requested_samples']} valid frames), "
        f"above the {args.depth_min_m:.3f} m hard no-go limit. This supports, but does not replace, "
        "the operator's short-corridor check."
    )


def depth_context_for_model(args: argparse.Namespace) -> str:
    """Collect OpenCV-mode depth context before the LLM decision."""
    if not args.depth_gate:
        return "No depth telemetry was requested for this step."
    return depth_context_from_statistics(args, read_depth_statistics(args))


def execute_supervised_action(
    args: argparse.Namespace,
    camera: RobotCamera | OrbbecSnapshotCamera,
    camera_source: int | str,
    agent: LLMAgent,
) -> tuple[bool, RobotCamera]:
    """Execute one fixed base step only after two explicit human confirmations."""
    if REQUESTED_ACTION is None:
        print("Gemini requested no permitted base action; no hardware command will be sent.")
        return False, camera

    if args.depth_gate and REQUESTED_ACTION == "forward_1s":
        if isinstance(camera, OrbbecSnapshotCamera):
            # A fresh, same-pipeline RGB-D snapshot immediately precedes the
            # human MOVE gate. It does not interact with OpenCV at all.
            forward_allowed = depth_allows_statistics(args, camera.capture_snapshot())
        else:
            # Gemini RGB and Orbbec SDK depth share one physical camera.
            camera.release()
            try:
                forward_allowed = depth_allows_forward(args)
            finally:
                camera = open_live_camera(camera_source)
                agent.main_camera = camera
        if not forward_allowed:
            print("No motor command sent.")
            return False, camera

    labels = {
        "forward_1s": "one keyboard-W forward step (1 second)",
        "turn_left_small": "one keyboard-Q small left turn (about 16°)",
        "turn_right_small": "one keyboard-E small right turn (about 16°)",
    }
    print(f"\nGemini requested {labels[REQUESTED_ACTION]}.")
    print("Check the motion area again: no person, pet, cable, stair edge, or obstacle in the action path.")
    confirmation = input("Type MOVE to permit this one physical step; any other input ends navigation: ").strip()
    if confirmation != "MOVE":
        print("Physical step cancelled. No motor command sent; navigation ends.")
        return False, camera

    print("Launching the independently tested fixed-motion script. It will require MOVE once more.")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "base_motion_step.py"), REQUESTED_ACTION],
        check=False,
    )
    if result.returncode != 0:
        print(f"Motion script ended with status {result.returncode}; navigation ends.")
        return False, camera
    return True, camera


def print_target_approach_handoff(args: argparse.Namespace) -> None:
    """Print the deterministic perception handoff selected by the LLM.

    The LLM chooses only a constrained semantic request. Target association,
    depth and all future stopping logic remain in the local perception layer.
    This function deliberately does not start a motor process.
    """
    assert REQUESTED_TARGET_APPROACH is not None
    target_label, standoff_m = REQUESTED_TARGET_APPROACH
    command = [
        "python",
        "tools/yolo_orbbec_depth_detect.py",
        "--depth-sudo",
        "--target",
        target_label,
        "--dry-run-approach",
        "--standoff-m",
        f"{standoff_m:.2f}",
    ]
    print("\nLLM high-level request accepted; handing off to local perception only.")
    print(f"  target={target_label}, requested standoff={standoff_m:.2f} m")
    print("  The following command displays TRACKING / FORWARD / TURN / STOP; it cannot move the robot:")
    print(f"  {shlex.join(command)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera",
        default="2",
        help="OpenCV camera index (default: head RGB camera 2 on this Mac), or Linux path such as /dev/camera_center.",
    )
    parser.add_argument(
        "--camera-backend",
        choices=("opencv", "orbbec"),
        default="opencv",
        help="Head-camera backend: OpenCV UVC, or one Orbbec SDK RGB-D snapshot per decision (default: opencv).",
    )
    parser.add_argument("--task", default=DEFAULT_TASK, help="One-shot task for Gemini.")
    parser.add_argument(
        "--supervised-forward",
        action="store_true",
        help="Compatibility mode: execute at most one supervised action.",
    )
    parser.add_argument(
        "--target-approach-dry-run",
        action="store_true",
        help="Offer Gemini a constrained high-level inanimate-target handoff tool; it only prints a local YOLO dry-run command.",
    )
    parser.add_argument(
        "--supervised-steps",
        action="store_true",
        help="Run a multi-step visual navigation loop; every action requires two human MOVE confirmations.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=3,
        choices=range(1, 4),
        metavar="1..3",
        help="Maximum physical actions in --supervised-steps mode (default: 3).",
    )
    parser.add_argument(
        "--depth-gate",
        action="store_true",
        help="Before each supervised forward step, require a fresh Gemini 335 center-ROI depth reading above --depth-min-m.",
    )
    parser.add_argument(
        "--depth-min-m",
        type=float,
        default=0.20,
        help="Hard no-go distance for --depth-gate in metres (default: 0.20). This does not replace the human MOVE check.",
    )
    parser.add_argument(
        "--depth-samples",
        type=int,
        default=15,
        help="Valid Gemini depth frames collected per forward safety check (default: 15).",
    )
    parser.add_argument(
        "--depth-timeout-s",
        type=int,
        default=30,
        help="Maximum seconds allowed for one depth safety check (default: 30).",
    )
    parser.add_argument(
        "--depth-python",
        default=str(DEFAULT_DEPTH_PYTHON),
        help="Python executable in the isolated orbbec-depth environment.",
    )
    parser.add_argument(
        "--depth-sudo",
        action="store_true",
        help="Prefix the depth read with sudo -E (usually needed for Gemini capture on this Mac).",
    )
    args = parser.parse_args()
    if args.depth_min_m <= 0 or args.depth_samples < 1 or args.depth_timeout_s < 1:
        raise SystemExit("--depth-min-m、--depth-samples 与 --depth-timeout-s 必须为正数。")

    require_api_key()
    camera_source = parse_camera(args.camera)
    camera: RobotCamera | OrbbecSnapshotCamera
    if args.camera_backend == "orbbec":
        camera = OrbbecSnapshotCamera(args)
    else:
        camera = open_live_camera(camera_source)

    available_tools = [move_forward_one_second, turn_left_small, turn_right_small, report_no_action]
    if args.target_approach_dry_run:
        available_tools.insert(3, request_target_approach)

    agent = LLMAgent(
        model="google_genai:gemini-3-flash-preview",
        tools=available_tools,
        main_camera=camera,
        name="xlerobot-safe-visual-navigation",
        system_prompt=SYSTEM_PROMPT,
        camera_fov=90,
        thinking_level="low",
        history_len=1,
    )
    supervised = args.supervised_forward or args.supervised_steps
    max_steps = 1 if args.supervised_forward else args.max_steps

    print("Safe LLM navigation test. Camera is live; actions are DRY RUN unless supervised mode is enabled.")
    try:
        for step in range(1, max_steps + 1):
            global REQUESTED_ACTION, REQUESTED_TARGET_APPROACH
            REQUESTED_ACTION = None
            REQUESTED_TARGET_APPROACH = None
            if args.camera_backend == "orbbec":
                # Capture before setting agent.task so Gemini receives RGB
                # and the corresponding depth geometry from one SDK frame set.
                statistics = camera.capture_snapshot()
                if statistics is None:
                    print("No fresh Orbbec RGB-D frame is available; ending navigation safely.")
                    break
                depth_context = depth_context_from_statistics(args, statistics)
            elif supervised and args.depth_gate:
                # Do not hold Gemini RGB UVC while the Orbbec SDK opens its
                # depth stream; macOS may otherwise provide neither stream.
                camera.release()
                try:
                    depth_context = depth_context_for_model(args)
                finally:
                    camera = open_live_camera(camera_source)
                    agent.main_camera = camera
            else:
                depth_context = ""
            agent.task = (
                f"{args.task}\n\nThis is supervised navigation step {step} of {max_steps}. "
                "Use only the newest image.\n\n"
                f"{depth_context}"
            )
            print(f"\n=== Visual navigation step {step}/{max_steps} ===")
            agent.main_loop_content()

            if REQUESTED_TARGET_APPROACH is not None:
                print_target_approach_handoff(args)
                break

            if not supervised:
                break
            action_completed, camera = execute_supervised_action(args, camera, camera_source, agent)
            if not action_completed:
                break
    finally:
        camera.release()
        agent.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
