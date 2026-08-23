"""Safely pick the detected blue cylinder with a real XLeRobot right arm.

The task mirrors ``xlerobot/scripts/pick_near_cylinder.py``:

1. acquire a stable RGB-D cylinder centroid;
2. transform color-camera optical coordinates directly into the right
   ``shoulder_lift`` pivot frame;
3. move above the target (transit);
4. descend vertically (approach), close, lift, and hold.

Dry-run is the default. Physical motion requires both ``--execute`` and a
robot-specific configuration whose ``calibrated`` field is true.
"""

from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from gemini335 import Gemini335Camera
from perception import DetectorConfig, annotate, detect_blue_cylinder


JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")

ROBOT_IMPORTS = (
    ("lerobot.robots.so_follower.so_follower", "lerobot.robots.so_follower.config_so_follower",
     "SO100Follower", "SO100FollowerConfig"),
    ("lerobot.robots.so101_follower.so101_follower",
     "lerobot.robots.so101_follower.config_so101_follower", "SO101Follower", "SO101FollowerConfig"),
    ("lerobot.robots.so101_follower", "lerobot.robots.so101_follower",
     "SO101Follower", "SO101FollowerConfig"),
    ("lerobot.robots.so100_follower", "lerobot.robots.so100_follower",
     "SO100Follower", "SO100FollowerConfig"),
)


class SafetyError(RuntimeError):
    """Raised when a physical-motion precondition or runtime check fails."""


@dataclass(frozen=True)
class PickPlan:
    target_camera_m: tuple[float, float, float] | None
    raw_target_shoulder_m: tuple[float, float, float]
    target_shoulder_m: tuple[float, float, float]
    grasp_shoulder_m: tuple[float, float, float]
    overhead_shoulder_m: tuple[float, float, float]
    lift_shoulder_m: tuple[float, float, float]
    overhead_joints_deg: dict[str, float]
    grasp_joints_deg: dict[str, float]
    lift_joints_deg: dict[str, float]
    centroid_spread_m: float
    samples: int


def _vector3(value: Any, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain three finite numbers")
    return result


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "calibrated",
        "camera_to_shoulder_4x4",
        "target_offset_shoulder_m",
        "kinematics",
        "motion",
        "joint_limits_deg",
        "gripper",
    }
    missing = required - config.keys()
    if missing:
        raise ValueError(f"Missing config fields: {sorted(missing)}")
    matrix = np.asarray(config["camera_to_shoulder_4x4"], dtype=np.float64)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("camera_to_shoulder_4x4 must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8):
        raise ValueError("camera_to_shoulder_4x4 last row must be [0, 0, 0, 1]")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=2e-2):
        raise ValueError("camera_to_shoulder rotation is not orthonormal")
    _vector3(config["target_offset_shoulder_m"], "target_offset_shoulder_m")
    return config


def transform_point(matrix_4x4: np.ndarray, point_xyz: np.ndarray) -> np.ndarray:
    homogeneous = np.append(_vector3(point_xyz, "point_xyz"), 1.0)
    return (np.asarray(matrix_4x4, dtype=np.float64) @ homogeneous)[:3]


def target_frame_coordinates(
    target_camera_m: np.ndarray,
    config: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Return raw centroid and offset-adjusted target in the shoulder/base frame."""
    raw_target_shoulder = transform_point(
        np.asarray(config["camera_to_shoulder_4x4"], dtype=np.float64),
        target_camera_m,
    )
    target_offset = _vector3(
        config["target_offset_shoulder_m"], "target_offset_shoulder_m"
    )
    return raw_target_shoulder, raw_target_shoulder + target_offset


def validate_fake_target_base(
    values: list[float] | tuple[float, float, float],
) -> np.ndarray:
    """Validate one manually supplied centroid in the shoulder/base frame."""
    return _vector3(values, "--fake-target base-frame xyz")


def planar_ik(x_m: float, z_m: float, l1_m: float, l2_m: float) -> tuple[float, float, float]:
    """Solve the upward-folding planar arm in the newly calibrated coordinates.

    ``shoulder_lift`` is zero along +x and +90 degrees along +z.
    The second return value is the geometric elbow internal angle: 180 degrees
    when straight, 90 degrees when perpendicular, and zero when folded. The
    caller converts it to the robot's +90..-90 ``elbow_flex`` convention. The
    returned third value is the forearm absolute pitch.
    """
    radius = math.hypot(x_m, z_m)
    lower = abs(l1_m - l2_m) + 1e-4
    upper = l1_m + l2_m - 1e-4
    if not lower <= radius <= upper:
        raise SafetyError(
            f"Planar wrist target is unreachable: radius={radius:.4f} m, "
            f"allowed=[{lower:.4f}, {upper:.4f}] m"
        )
    cos_bend = (radius**2 - l1_m**2 - l2_m**2) / (2.0 * l1_m * l2_m)
    bend = math.acos(float(np.clip(cos_bend, -1.0, 1.0)))
    # Select the physical branch where the forearm folds upward from the upper
    # arm. The mirrored branch (forearm below the upper arm) cannot occur.
    shoulder = math.atan2(z_m, x_m) - math.atan2(
        l2_m * math.sin(bend), l1_m + l2_m * math.cos(bend)
    )
    forearm_pitch = shoulder + bend
    elbow_internal = math.pi - bend
    return (
        math.degrees(shoulder),
        math.degrees(elbow_internal),
        math.degrees(forearm_pitch),
    )


def model_joint_to_motor(name: str, model_angle_deg: float, config: dict) -> float:
    """Convert one model-coordinate joint angle to a LeRobot motor command."""
    sign = float(config.get("joint_command_signs", {}).get(name, 1.0))
    if sign not in (-1.0, 1.0):
        raise SafetyError(f"joint command sign must be -1 or +1: {name}={sign}")
    offset = float(config.get("joint_command_offsets_deg", {}).get(name, 0.0))
    return sign * float(model_angle_deg) + offset


def relative_ee_to_joints(
    point_shoulder_m: np.ndarray,
    config: dict,
    tool_pitch_deg: float | None = None,
) -> dict[str, float]:
    """Convert a gripper-center point relative to the shoulder pivot to joints.

    Frame: +x points along shoulder_pan=0, +y is positive pan (counter-clockwise
    around +z), and +z points upward. Tool pitch is measured from horizontal +x.
    """
    relative = _vector3(point_shoulder_m, "point_shoulder_m")
    kin = config["kinematics"]
    dx, dy, dz = map(float, relative)
    radial = math.hypot(dx, dy)
    pan = math.degrees(math.atan2(dy, dx))
    pitch_deg = float(kin.get("tool_pitch_deg", 0.0) if tool_pitch_deg is None else tool_pitch_deg)
    if not math.isfinite(pitch_deg):
        raise SafetyError("tool pitch must be finite")
    pitch = math.radians(pitch_deg)
    tool_length = float(kin["tool_length_m"])
    wrist_x = radial - tool_length * math.cos(pitch)
    wrist_z = dz - tool_length * math.sin(pitch)
    shoulder_lift, elbow_internal, forearm_pitch = planar_ik(
        wrist_x, wrist_z, float(kin["upper_arm_m"]), float(kin["lower_arm_m"])
    )
    # Robot elbow convention: folded=+90, perpendicular=0, straight=-90.
    elbow_flex = 90.0 - elbow_internal
    # Calibrated wrist convention: folded parallel=-180, perpendicular=-90,
    # and straight outward=0. Start from the 0..180 internal angle and shift it.
    wrist_internal = math.degrees(
        math.acos(float(np.clip(-math.cos(pitch - math.radians(forearm_pitch)), -1.0, 1.0)))
    )
    wrist_flex = wrist_internal - 180.0
    joints = {
        "shoulder_pan": pan,
        "shoulder_lift": shoulder_lift,
        "elbow_flex": elbow_flex,
        "wrist_flex": wrist_flex,
        "wrist_roll": float(kin.get("wrist_roll_deg", 90.0)),
    }
    for name in joints:
        joints[name] = model_joint_to_motor(name, joints[name], config)
    validate_joint_targets(joints, config)
    return joints


def cartesian_to_joints(point_shoulder_m: np.ndarray, config: dict) -> dict[str, float]:
    """Convert a grasp-center target in the shoulder-pivot frame to motor degrees."""
    return relative_ee_to_joints(point_shoulder_m, config)


def validate_joint_targets(targets: dict[str, float], config: dict) -> None:
    for name, value in targets.items():
        if not math.isfinite(float(value)):
            raise SafetyError(f"Non-finite joint target: {name}={value}")
        if name not in config["joint_limits_deg"]:
            raise SafetyError(f"No configured safety limit for joint {name}")
        low, high = map(float, config["joint_limits_deg"][name])
        if not low <= float(value) <= high:
            raise SafetyError(f"{name}={value:.2f} deg outside configured [{low}, {high}]")


def build_plan_from_base_centroid(
    raw_target_shoulder_m: np.ndarray,
    spread_m: float,
    samples: int,
    config: dict,
    *,
    target_camera_m: np.ndarray | None = None,
) -> PickPlan:
    """Build the complete pick from a centroid already expressed in base frame."""
    raw_target_shoulder = _vector3(
        raw_target_shoulder_m, "raw base-frame target centroid"
    )
    target_shoulder = raw_target_shoulder + _vector3(
        config["target_offset_shoulder_m"], "target_offset_shoulder_m"
    )
    motion = config["motion"]
    grasp = target_shoulder + _vector3(
        motion.get("grasp_offset_shoulder_m", [0, 0, 0]), "shoulder-frame grasp offset"
    )
    overhead = grasp + np.array([0.0, 0.0, float(motion["approach_height_m"])])
    lift = grasp + np.array([0.0, 0.0, float(motion["lift_height_m"])])
    overhead_joints = cartesian_to_joints(overhead, config)
    grasp_joints = cartesian_to_joints(grasp, config)
    lift_joints = cartesian_to_joints(lift, config)
    gripper_open = float(config["gripper"]["open_deg"])
    for target in (overhead_joints, grasp_joints, lift_joints):
        target["gripper"] = gripper_open
        validate_joint_targets(target, config)
    return PickPlan(
        target_camera_m=(
            tuple(map(float, target_camera_m)) if target_camera_m is not None else None
        ),
        raw_target_shoulder_m=tuple(map(float, raw_target_shoulder)),
        target_shoulder_m=tuple(map(float, target_shoulder)),
        grasp_shoulder_m=tuple(map(float, grasp)),
        overhead_shoulder_m=tuple(map(float, overhead)),
        lift_shoulder_m=tuple(map(float, lift)),
        overhead_joints_deg=overhead_joints,
        grasp_joints_deg=grasp_joints,
        lift_joints_deg=lift_joints,
        centroid_spread_m=float(spread_m),
        samples=int(samples),
    )


def build_plan(
    target_camera_m: np.ndarray,
    spread_m: float,
    samples: int,
    config: dict,
) -> PickPlan:
    """Build the complete pick from one color-camera optical-frame centroid."""
    raw_target_shoulder, _ = target_frame_coordinates(target_camera_m, config)
    return build_plan_from_base_centroid(
        raw_target_shoulder,
        spread_m,
        samples,
        config,
        target_camera_m=target_camera_m,
    )


def save_detection_contact_sheet(views: list[np.ndarray], output_path: Path) -> None:
    """Save accepted detections in one image for post-run diagnosis."""
    if not views:
        return
    columns = min(2, len(views))
    tile_width = 960
    first_height, first_width = views[0].shape[:2]
    tile_height = max(1, round(first_height * tile_width / first_width))
    rows = math.ceil(len(views) / columns)
    sheet = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)
    for index, view in enumerate(views):
        tile = cv2.resize(view, (tile_width, tile_height), interpolation=cv2.INTER_AREA)
        row, column = divmod(index, columns)
        y = row * tile_height
        x = column * tile_width
        sheet[y : y + tile_height, x : x + tile_width] = tile
    cv2.imwrite(str(output_path), sheet)


def acquire_stable_target(camera: Gemini335Camera, args, output_dir: Path):
    intrinsics = camera.start()
    detector = DetectorConfig(
        hsv_lower=(args.hue_low, 70, 35),
        hsv_upper=(args.hue_high, 255, 255),
        min_area_px=args.min_area,
        min_depth_m=args.min_depth,
        max_depth_m=args.max_depth,
        cylinder_radius_m=args.radius,
    )
    samples: list[np.ndarray] = []
    accepted_views: list[np.ndarray] = []
    deadline = time.monotonic() + args.acquisition_timeout
    last_bgr = last_depth = last_mask = last_detection = None
    print(f"[PERCEPTION] collecting {args.samples} stable detections...")
    while time.monotonic() < deadline and len(samples) < args.samples:
        frame = camera.read()
        if frame is None:
            continue
        bgr, depth = frame
        detection, mask = detect_blue_cylinder(bgr, depth, intrinsics, detector)
        last_bgr, last_depth, last_mask, last_detection = bgr, depth, mask, detection
        if detection is not None and detection.confidence >= args.min_confidence:
            point = np.asarray(detection.cylinder_center_estimate_m, dtype=np.float64)
            samples.append(point)
            diagnostic_view = annotate(bgr, mask, detection, intrinsics)
            cv2.putText(
                diagnostic_view,
                f"accepted {len(samples):02d}/{args.samples}  xyz={np.round(point, 4).tolist()}  "
                f"conf={detection.confidence:.2f}",
                (20, diagnostic_view.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 255, 255),
                3,
                cv2.LINE_AA,
            )
            accepted_views.append(diagnostic_view)
            print(
                f"[PERCEPTION {len(samples):02d}/{args.samples}] "
                f"camera_xyz={np.round(samples[-1], 4).tolist()} conf={detection.confidence:.2f}"
            )
        if not args.no_preview:
            view = annotate(bgr, mask, detection, intrinsics)
            cv2.imshow("XLeRobot real pick acquisition | ESC abort", view)
            if cv2.waitKey(1) & 0xFF == 27:
                raise KeyboardInterrupt

    if last_bgr is not None:
        cv2.imwrite(str(output_dir / "acquisition_rgb.png"), last_bgr)
        cv2.imwrite(str(output_dir / "acquisition_mask.png"), last_mask)
        cv2.imwrite(
            str(output_dir / "acquisition_annotated.png"),
            annotate(last_bgr, last_mask, last_detection, intrinsics),
        )
        np.save(output_dir / "acquisition_depth_m.npy", last_depth)
    contact_sheet_path = output_dir / "acquisition_detections.png"
    save_detection_contact_sheet(accepted_views, contact_sheet_path)
    if accepted_views:
        print(f"[PERCEPTION] accepted-detection image saved to {contact_sheet_path}")

    if len(samples) < args.samples:
        raise SafetyError(f"Perception timeout: received {len(samples)}/{args.samples} valid detections")
    stacked = np.stack(samples)
    target = np.median(stacked, axis=0)
    spread = float(np.max(np.linalg.norm(stacked - target, axis=1)))
    if spread > args.max_spread:
        raise SafetyError(f"Unstable centroid: max spread {spread:.4f} m > {args.max_spread:.4f} m")
    print(f"[PERCEPTION] stable camera centroid={target.tolist()}, max_spread={spread:.5f} m")
    return target, spread


def import_robot_classes():
    attempts = []
    for robot_module, config_module, robot_name, config_name in ROBOT_IMPORTS:
        try:
            rmod = __import__(robot_module, fromlist=[robot_name])
            cmod = __import__(config_module, fromlist=[config_name])
            return getattr(rmod, robot_name), getattr(cmod, config_name)
        except (ImportError, AttributeError) as exc:
            attempts.append(f"{robot_module}: {exc}")
    raise RuntimeError("Cannot import a supported LeRobot SO100/SO101 follower:\n" + "\n".join(attempts))


def make_robot(port: str, robot_id: str):
    robot_class, config_class = import_robot_classes()
    parameters = inspect.signature(config_class).parameters
    kwargs = {"port": port}
    if "id" in parameters:
        kwargs["id"] = robot_id
    return robot_class(config_class(**kwargs))


def connect_without_calibration(robot) -> None:
    parameters = inspect.signature(robot.connect).parameters
    if "calibrate" in parameters:
        robot.connect(calibrate=False)
    else:
        robot.connect()


def disconnect_robot(robot) -> None:
    """Disconnect while preserving the result if torque-disable communication fails."""
    try:
        robot.disconnect()
    except ConnectionError as exc:
        print(f"[ROBOT] WARNING: disconnect failed: {exc}", file=sys.stderr)
        print("[ROBOT] Torque may still be enabled; support the arm and check power/bus wiring.", file=sys.stderr)


def read_joint_positions(robot) -> dict[str, float]:
    observation = robot.get_observation()
    result = {}
    for name in JOINTS:
        key = f"{name}.pos"
        if key in observation:
            value = observation[key]
            result[name] = float(value.item() if hasattr(value, "item") else value)
    missing = set(JOINTS) - result.keys()
    if missing:
        raise SafetyError(f"Robot observation is missing joints: {sorted(missing)}; keys={sorted(observation)}")
    return result


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def run_control_loop(
    robot,
    command_at: Callable[[float], dict[str, float]],
    start: dict[str, float],
    duration_s: float,
    config: dict,
    phase: str,
) -> None:
    """Send one smooth, bounded trajectory and monitor tracking error."""
    frequency = float(config["motion"]["control_hz"])
    steps = max(2, int(duration_s * frequency))
    max_step = float(config["motion"]["max_command_step_deg"])
    max_tracking_error = float(config["motion"]["max_tracking_error_deg"])
    previous = start.copy()

    for step in range(1, steps + 1):
        desired = command_at(smoothstep(step / steps))
        validate_joint_targets(desired, config)
        for name in JOINTS:
            delta = float(desired[name]) - previous[name]
            if abs(delta) > max_step + 1e-9:
                raise SafetyError(f"{phase}: {name} step {delta:.2f} deg exceeds {max_step:.2f}")
        previous = {name: float(desired[name]) for name in JOINTS}
        robot.send_action({f"{name}.pos": value for name, value in previous.items()})

        if step > max(2, int(0.5 * frequency)) and step % max(1, int(frequency / 5)) == 0:
            measured = read_joint_positions(robot)
            error = max(abs(measured[name] - previous[name]) for name in JOINTS)
            if error > max_tracking_error:
                raise SafetyError(
                    f"{phase}: tracking error {error:.1f} deg exceeds {max_tracking_error:.1f}; aborting"
                )
        time.sleep(1.0 / frequency)


def execute_trajectory(robot, target: dict[str, float], duration_s: float, config: dict, phase: str) -> None:
    """Interpolate directly between two joint poses."""
    validate_joint_targets(target, config)
    start = read_joint_positions(robot)
    print(f"[PHASE] {phase}: duration={duration_s:.1f}s target={target}")

    def command_at(alpha: float) -> dict[str, float]:
        return {
            name: start[name] + alpha * (float(target[name]) - start[name])
            for name in JOINTS
        }

    run_control_loop(robot, command_at, start, duration_s, config, phase)


def execute_cartesian_trajectory(
    robot,
    start_shoulder_m: tuple[float, float, float],
    target_shoulder_m: tuple[float, float, float],
    gripper_deg: float,
    duration_s: float,
    config: dict,
    phase: str,
) -> None:
    """Follow a Cartesian line, solving IK at every control cycle."""
    start_xyz = _vector3(start_shoulder_m, "shoulder-frame Cartesian start")
    target_xyz = _vector3(target_shoulder_m, "shoulder-frame Cartesian target")
    measured_start = read_joint_positions(robot)
    # The motor bus is still holding the final command from the preceding
    # phase.  Use that commanded Cartesian waypoint as the command-step
    # baseline; using the measured pose here incorrectly turns normal servo
    # tracking lag into an apparent first-command jump.  Actual-vs-commanded
    # error remains protected independently by max_tracking_error_deg.
    commanded_start = cartesian_to_joints(start_xyz, config)
    commanded_start["gripper"] = float(gripper_deg)
    start_errors = {
        name: measured_start[name] - commanded_start[name]
        for name in JOINTS
    }
    print(
        f"[PHASE] {phase}: Cartesian {start_xyz.tolist()} -> {target_xyz.tolist()}, "
        f"duration={duration_s:.1f}s"
    )
    print(
        f"[PHASE] {phase}: measured-minus-commanded start errors deg="
        f"{json.dumps(start_errors, sort_keys=True)}"
    )

    def command_at(alpha: float) -> dict[str, float]:
        xyz = start_xyz + alpha * (target_xyz - start_xyz)
        desired = cartesian_to_joints(xyz, config)
        desired["gripper"] = float(gripper_deg)
        return desired

    run_control_loop(robot, command_at, commanded_start, duration_s, config, phase)


def inspect_robot(port: str, robot_id: str) -> None:
    if not port:
        raise SafetyError("--port is required with --init_only")
    robot = make_robot(port, robot_id)
    connected = False
    try:
        connect_without_calibration(robot)
        connected = True
        initial_joints = read_joint_positions(robot)
        print(f"[INIT] measured joints={json.dumps(initial_joints, sort_keys=True)}")
        print("[INIT] read-only inspection completed; no send_action call was made")
    finally:
        if connected:
            disconnect_robot(robot)


def execute_joint_test(
    config: dict,
    port: str,
    robot_id: str,
    requested_targets: dict[str, float | None],
    duration_s: float,
) -> None:
    """Test model-to-motor mapping without camera, Cartesian targets, or IK."""
    if not port:
        raise SafetyError("--port is required with --joint_test")
    if not config["calibrated"]:
        raise SafetyError("Config calibrated=false; refusing joint-test motion")
    if not math.isfinite(duration_s):
        raise SafetyError("joint-test duration must be finite")
    if not 2.0 <= duration_s <= 60.0:
        raise SafetyError("--joint-test-duration must be between 2 and 60 seconds")

    model_targets = {name: value for name, value in requested_targets.items() if value is not None}
    if not model_targets:
        model_targets = {"shoulder_lift": 20.0, "elbow_flex": -30.0}
        print("[JOINT TEST] no joint target supplied; using shoulder_lift=20, elbow_flex=-30")
    if not all(math.isfinite(float(value)) for value in model_targets.values()):
        raise SafetyError("joint-test targets must be finite")

    motor_targets = {}
    for name, value in model_targets.items():
        motor_targets[name] = (
            float(value) if name == "gripper" else model_joint_to_motor(name, value, config)
        )
    print(
        "[JOINT TEST] camera, perception, camera_to_shoulder, Cartesian target, and IK are bypassed"
    )
    print(f"[JOINT TEST] requested target={json.dumps(model_targets, sort_keys=True)}")
    print(f"[JOINT TEST] converted motor target={json.dumps(motor_targets, sort_keys=True)}")

    robot = make_robot(port, robot_id)
    connected = False
    try:
        connect_without_calibration(robot)
        connected = True
        start = read_joint_positions(robot)
        target = start.copy()
        target.update(motor_targets)
        validate_joint_targets(start, config)
        validate_joint_targets(target, config)
        deltas = {name: motor_targets[name] - start[name] for name in motor_targets}
        print(f"[JOINT TEST] initial measured joints={json.dumps(start, sort_keys=True)}")
        print(f"[JOINT TEST] motor deltas={json.dumps(deltas, sort_keys=True)}")
        large_moves = {name: delta for name, delta in deltas.items() if abs(delta) > 45.0}
        if large_moves:
            print(f"[JOINT TEST] WARNING: motor moves over 45 deg={json.dumps(large_moves, sort_keys=True)}")
        held = sorted(set(JOINTS) - motor_targets.keys())
        print(f"[JOINT TEST] joints held at initial values={held}")
        try:
            answer = input(
                f"[JOINT TEST] Press Enter to move over {duration_s:.1f}s; "
                "type anything else to abort: "
            )
        except EOFError as exc:
            raise SafetyError("joint test requires an interactive terminal") from exc
        if answer != "":
            raise SafetyError("operator aborted joint test before motion")

        execute_trajectory(robot, target, duration_s, config, "joint_test")
        measured = stage_checkpoint(robot, "joint_test", target, None)
        model_estimate = {}
        for name in motor_targets:
            if name == "gripper":
                model_estimate[name] = measured[name]
            else:
                sign = float(config.get("joint_command_signs", {}).get(name, 1.0))
                offset = float(config.get("joint_command_offsets_deg", {}).get(name, 0.0))
                model_estimate[name] = sign * (measured[name] - offset)
        print(f"[JOINT TEST] measured model-coordinate estimate={json.dumps(model_estimate, sort_keys=True)}")
        try:
            input(
                "[JOINT TEST] Motors are holding the test pose. Inspect/photograph it, "
                "then press Enter to disconnect: "
            )
        except EOFError:
            pass
    finally:
        if connected:
            disconnect_robot(robot)
            print("[ROBOT] disconnected; verify whether your motor model releases torque on disconnect")


def execute_ee_test(
    config: dict,
    port: str,
    robot_id: str,
    point_shoulder_m: np.ndarray,
    tool_pitch_deg: float,
    duration_s: float,
) -> None:
    """Move to an end-effector point expressed in the shoulder-pivot frame."""
    if not port:
        raise SafetyError("--port is required with --ee_test")
    if not config["calibrated"]:
        raise SafetyError("Config calibrated=false; refusing end-effector test motion")
    if not math.isfinite(duration_s) or not 2.0 <= duration_s <= 60.0:
        raise SafetyError("--ee-test-duration must be between 2 and 60 seconds")

    point = _vector3(point_shoulder_m, "test end-effector point")
    motor_targets = relative_ee_to_joints(point, config, tool_pitch_deg)
    print("[EE TEST] camera, perception, camera_to_shoulder, and detected target are bypassed")
    print("[EE TEST] frame origin=shoulder_lift pivot; +x=pan 0, +y=positive pan, +z=up")
    print(
        f"[EE TEST] target relative to shoulder pivot m={point.tolist()} "
        f"tool_pitch_deg={tool_pitch_deg:.2f}"
    )
    print(f"[EE TEST] IK motor target={json.dumps(motor_targets, sort_keys=True)}")

    robot = make_robot(port, robot_id)
    connected = False
    try:
        connect_without_calibration(robot)
        connected = True
        start = read_joint_positions(robot)
        target = start.copy()
        target.update(motor_targets)
        validate_joint_targets(start, config)
        validate_joint_targets(target, config)
        deltas = {name: target[name] - start[name] for name in motor_targets}
        print(f"[EE TEST] initial measured joints={json.dumps(start, sort_keys=True)}")
        print(f"[EE TEST] motor deltas={json.dumps(deltas, sort_keys=True)}")
        print(
            f"[EE TEST] wrist_roll will move to configured {motor_targets['wrist_roll']:.2f} deg; "
            "gripper will hold its initial value"
        )
        large_moves = {name: delta for name, delta in deltas.items() if abs(delta) > 45.0}
        if large_moves:
            print(f"[EE TEST] WARNING: motor moves over 45 deg={json.dumps(large_moves, sort_keys=True)}")
        try:
            answer = input(
                f"[EE TEST] Press Enter to move over {duration_s:.1f}s; "
                "type anything else to abort: "
            )
        except EOFError as exc:
            raise SafetyError("end-effector test requires an interactive terminal") from exc
        if answer != "":
            raise SafetyError("operator aborted end-effector test before motion")

        execute_trajectory(robot, target, duration_s, config, "ee_test")
        stage_checkpoint(robot, "ee_test", target, None)
        try:
            input(
                "[EE TEST] Motors are holding the test pose. Measure/photograph it, "
                "then press Enter to disconnect: "
            )
        except EOFError:
            pass
    finally:
        if connected:
            disconnect_robot(robot)
            print("[ROBOT] disconnected; verify whether your motor model releases torque on disconnect")


def print_ee_test_plan(config: dict, point_shoulder_m: np.ndarray, tool_pitch_deg: float) -> None:
    point = _vector3(point_shoulder_m, "test end-effector point")
    targets = relative_ee_to_joints(point, config, tool_pitch_deg)
    print("[EE TEST] camera, perception, camera_to_shoulder, and detected target are bypassed")
    print("[EE TEST] frame origin=shoulder_lift pivot; +x=pan 0, +y=positive pan, +z=up")
    print(
        f"[EE TEST] target relative to shoulder pivot m={point.tolist()} "
        f"tool_pitch_deg={tool_pitch_deg:.2f}"
    )
    print(f"[EE TEST] IK motor target={json.dumps(targets, sort_keys=True)}")


def stage_checkpoint(
    robot,
    stage: str,
    target: dict[str, float] | None,
    next_stage: str | None,
) -> dict[str, float]:
    """Print measured joints at a stage boundary and optionally wait for Enter."""
    measured = read_joint_positions(robot)
    print(f"[STAGE {stage}] measured joints={json.dumps(measured, sort_keys=True)}")
    if target is not None:
        errors = {name: measured[name] - float(target[name]) for name in JOINTS}
        worst_error = max(abs(value) for value in errors.values())
        print(f"[STAGE {stage}] target errors deg={json.dumps(errors, sort_keys=True)}")
        print(f"[STAGE {stage}] max absolute target error={worst_error:.2f} deg")

    if next_stage is not None:
        try:
            answer = input(
                f"[STAGE {stage}] Motors remain enabled and holding position. "
                f"Press Enter to continue to {next_stage}; type anything else to abort: "
            )
        except EOFError as exc:
            raise SafetyError(f"{stage}: terminal input closed; aborting staged execution") from exc
        if answer != "":
            raise SafetyError(f"{stage}: operator aborted before {next_stage}")
    return measured


def execute_pick(
    plan: PickPlan,
    config: dict,
    port: str,
    robot_id: str,
    duration_scale: float = 1.0,
    stage_test: bool = False,
) -> None:
    if not config["calibrated"]:
        raise SafetyError("Config calibrated=false; physical motion is locked")
    if not port:
        raise SafetyError("--port is required with --execute")
    if not math.isfinite(duration_scale) or not 1.0 <= duration_scale <= 10.0:
        raise SafetyError("--duration-scale must be between 1.0 and 10.0")
    robot = make_robot(port, robot_id)
    connected = False
    try:
        connect_without_calibration(robot)
        connected = True
        start = read_joint_positions(robot)
        print(f"[ROBOT] connected; measured joints={start}")
        validate_joint_targets(start, config)

        durations = config["motion"]["phase_duration_s"]
        open_value = float(config["gripper"]["open_deg"])
        closed_value = float(config["gripper"]["closed_deg"])
        overhead = plan.overhead_joints_deg | {"gripper": open_value}
        grasp_open = plan.grasp_joints_deg | {"gripper": open_value}
        grasp = plan.grasp_joints_deg | {"gripper": closed_value}
        lift = plan.lift_joints_deg | {"gripper": closed_value}

        def movement_duration(phase: str) -> float:
            return float(durations[phase]) * duration_scale

        print(
            f"[MOTION] duration scale={duration_scale:.2f}; "
            "movement durations are multiplied by this value"
        )
        if stage_test:
            stage_checkpoint(robot, "init", start, "transit (object overhead)")

        execute_trajectory(robot, overhead, movement_duration("transit"), config, "transit")
        if stage_test:
            stage_checkpoint(robot, "overhead", overhead, "approach (open gripper)")
        execute_cartesian_trajectory(
            robot, plan.overhead_shoulder_m, plan.grasp_shoulder_m, open_value,
            movement_duration("approach"), config, "approach"
        )
        if stage_test:
            stage_checkpoint(robot, "approach", grasp_open, "close gripper")
        execute_trajectory(robot, grasp, movement_duration("close"), config, "close")
        if stage_test:
            stage_checkpoint(robot, "closed", grasp, "lift")
        execute_cartesian_trajectory(
            robot, plan.grasp_shoulder_m, plan.lift_shoulder_m, closed_value,
            movement_duration("lift"), config, "lift"
        )
        if stage_test:
            stage_checkpoint(robot, "lifted", lift, "hold")
        print(f"[HOLD] holding lifted target for {durations['hold']:.1f}s")
        time.sleep(float(durations["hold"]))
        if stage_test:
            stage_checkpoint(robot, "complete", lift, None)
        print("[RESULT] motion sequence completed; object retention is not force-verified")
    finally:
        if connected:
            disconnect_robot(robot)
            print("[ROBOT] disconnected; verify whether your motor model releases torque on disconnect")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("pick_config_v1.json"),
        help="robot and motion configuration JSON",
    )
    parser.add_argument("--port", default=None, help="right-arm USB port, e.g. /dev/arm_right or COM5")
    parser.add_argument("--robot-id", default="xlerobot_right_arm")
    parser.add_argument("--execute", action="store_true", help="enable physical motion after all checks")
    parser.add_argument(
        "--allow-diagnostic-extrinsic",
        action="store_true",
        help=(
            "explicitly allow --execute with a diagnostic-only camera-to-shoulder matrix; "
            "unsafe until an independent white-arm validation passes"
        ),
    )
    parser.add_argument(
        "--duration-scale", type=float, default=1.0,
        help="multiply transit/approach/close/lift durations; 2.0 is approximately half speed (1-10)",
    )
    parser.add_argument(
        "--stage-test", action="store_true",
        help="print measured joints and wait for Enter at every physical-motion stage boundary",
    )
    parser.add_argument(
        "--init_only", "--init-only", "--inspect-robot",
        dest="init_only",
        action="store_true",
        help="only connect, print initial joint positions, and disconnect; camera and motors are not commanded",
    )
    parser.add_argument(
        "--joint_test", "--joint-test",
        dest="joint_test",
        action="store_true",
        help="bypass camera and IK; move only explicitly supplied --test-* joints",
    )
    for name in JOINTS:
        option = f"--test-{name.replace('_', '-')}"
        unit = "LeRobot degrees" if name == "gripper" else "model-coordinate degrees"
        parser.add_argument(option, dest=f"test_{name}", type=float, default=None, help=f"{name} target in {unit}")
    parser.add_argument(
        "--joint-test-duration", type=float, default=15.0,
        help="joint-test movement duration in seconds (2-60; default: 15)",
    )
    parser.add_argument(
        "--ee_test", "--ee-test",
        dest="ee_test",
        action="store_true",
        help="bypass camera; test IK for a gripper-center point relative to the shoulder pivot",
    )
    parser.add_argument("--test-ee-x", type=float, default=0.35, help="shoulder-frame +x target in metres")
    parser.add_argument("--test-ee-y", type=float, default=0.0, help="shoulder-frame +y target in metres")
    parser.add_argument("--test-ee-z", type=float, default=0.12, help="shoulder-frame +z target in metres")
    parser.add_argument(
        "--test-ee-pitch", type=float, default=0.0,
        help="tool pitch in degrees: 0=horizontal outward, -90=vertical downward",
    )
    parser.add_argument(
        "--ee-test-duration", type=float, default=15.0,
        help="end-effector test movement duration in seconds (2-60; default: 15)",
    )
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument(
        "--fake-target",
        type=float,
        nargs=3,
        metavar=("BASE_X_M", "BASE_Y_M", "BASE_Z_M"),
        help=(
            "bypass RGB-D detection and use one manual centroid in the shoulder-axis base frame "
            "(+x=pan 0, +y=positive pan, +z=up), in metres; physical execution requires --stage-test"
        ),
    )
    parser.add_argument(
        "--camera-warmup-frames",
        type=int,
        default=45,
        help="discard this many RGB-D frames before perception so auto exposure/white balance can settle",
    )
    parser.add_argument("--acquisition-timeout", type=float, default=20.0)
    parser.add_argument("--max-spread", type=float, default=0.012, help="metres")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--min-depth", type=float, default=0.10)
    parser.add_argument("--max-depth", type=float, default=1.50)
    parser.add_argument("--min-area", type=int, default=250)
    parser.add_argument("--radius", type=float, default=0.018)
    parser.add_argument("--hue-low", type=int, default=90)
    parser.add_argument("--hue-high", type=int, default=140)
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("pick_outputs"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    camera = None
    try:
        if args.init_only:
            inspect_robot(args.port, args.robot_id)
            return 0

        if not args.config.exists():
            raise ValueError(f"Missing config: {args.config}")
        config = load_config(args.config)
        extrinsic_status = str(config.get("camera_to_shoulder_status", "validated"))
        if extrinsic_status != "validated":
            source = str(config.get("camera_to_shoulder_source", "unspecified diagnostic source"))
            print(
                f"[CALIBRATION] WARNING: camera-to-shoulder status={extrinsic_status}; "
                f"source={source}"
            )

        selected_test_modes = sum(
            (bool(args.joint_test), bool(args.ee_test), args.fake_target is not None)
        )
        if selected_test_modes > 1:
            raise SafetyError("choose only one of --joint_test, --ee_test and --fake-target")

        if args.joint_test:
            if not args.execute:
                raise SafetyError("--joint_test requires --execute")
            if not sys.stdin.isatty():
                raise SafetyError("--joint_test requires an interactive terminal; use wrapper --interactive")
            execute_joint_test(
                config,
                args.port,
                args.robot_id,
                {name: getattr(args, f"test_{name}") for name in JOINTS},
                args.joint_test_duration,
            )
            return 0

        if args.ee_test:
            point = np.array([args.test_ee_x, args.test_ee_y, args.test_ee_z], dtype=np.float64)
            if not args.execute:
                print_ee_test_plan(config, point, args.test_ee_pitch)
                print("[EE TEST DRY-RUN] no robot connection or command was made")
                return 0
            if not sys.stdin.isatty():
                raise SafetyError("--ee_test requires an interactive terminal; use wrapper --interactive")
            execute_ee_test(
                config,
                args.port,
                args.robot_id,
                point,
                args.test_ee_pitch,
                args.ee_test_duration,
            )
            return 0

        if not math.isfinite(args.duration_scale) or not 1.0 <= args.duration_scale <= 10.0:
            raise SafetyError("--duration-scale must be between 1.0 and 10.0")
        if not 1 <= args.camera_warmup_frames <= 300:
            raise SafetyError("--camera-warmup-frames must be between 1 and 300")
        if args.stage_test and not args.execute:
            raise SafetyError("--stage-test requires --execute")
        if args.stage_test and not sys.stdin.isatty():
            raise SafetyError("--stage-test requires an interactive terminal; use wrapper --interactive")
        if args.fake_target is not None and args.execute and not args.stage_test:
            raise SafetyError("physical --fake-target execution requires --stage-test")
        if args.execute and not config["calibrated"]:
            raise SafetyError("Config calibrated=false; refusing to acquire or move in execute mode")
        output = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
        output.mkdir(parents=True, exist_ok=True)
        if args.fake_target is not None:
            raw_target_shoulder = validate_fake_target_base(args.fake_target)
            target_camera = None
            spread = 0.0
            target_samples = 1
            print(
                "[FAKE TARGET] bypassing Gemini acquisition; "
                f"base_frame_centroid={raw_target_shoulder.tolist()} m"
            )
        else:
            camera = Gemini335Camera(warmup_frames=args.camera_warmup_frames)
            target_camera, spread = acquire_stable_target(camera, args, output)
            target_samples = args.samples
            raw_target_shoulder, _ = target_frame_coordinates(target_camera, config)

        target_offset = _vector3(
            config["target_offset_shoulder_m"], "target_offset_shoulder_m"
        )
        target_shoulder = raw_target_shoulder + target_offset
        print(
            "[TRANSFORM] base_frame centroid="
            f"{raw_target_shoulder.tolist()} m; "
            "origin=shoulder_lift pivot, +x=pan 0, +y=positive pan, +z=up"
        )
        print(
            f"[TARGET] base_frame offset={target_offset.tolist()} m; "
            f"adjusted base_frame target={target_shoulder.tolist()} m"
        )
        plan = build_plan_from_base_centroid(
            raw_target_shoulder,
            spread,
            target_samples,
            config,
            target_camera_m=target_camera,
        )
        plan_path = output / "pick_plan.json"
        plan_path.write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
        print(json.dumps(asdict(plan), indent=2))
        print(f"[PLAN] saved {plan_path}")
        if not args.execute:
            print("[DRY-RUN] no motor connection or command was made. Add --execute only after calibration review.")
            return 0
        if extrinsic_status != "validated" and not args.allow_diagnostic_extrinsic:
            raise SafetyError(
                "camera_to_shoulder matrix is diagnostic-only; inspect the dry-run shoulder centroid first. "
                "Physical use requires --allow-diagnostic-extrinsic and close supervision."
            )
        if extrinsic_status != "validated":
            print(
                f"[CALIBRATION] WARNING: using {extrinsic_status} camera-to-shoulder matrix "
                "for physical motion"
            )
        execute_pick(
            plan,
            config,
            args.port,
            args.robot_id,
            duration_scale=args.duration_scale,
            stage_test=args.stage_test,
        )
        return 0
    except KeyboardInterrupt:
        print("\n[ABORT] operator interrupt")
        return 130
    except (SafetyError, RuntimeError, ValueError) as exc:
        print(f"[ABORT] {exc}", file=sys.stderr)
        return 2
    finally:
        if camera is not None:
            camera.stop()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
