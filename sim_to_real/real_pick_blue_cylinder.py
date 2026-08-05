"""Safely pick the detected blue cylinder with a real XLeRobot right arm.

The task mirrors ``xlerobot/scripts/pick_near_cylinder.py``:

1. acquire a stable RGB-D cylinder centroid;
2. transform color-camera optical coordinates into ``robot_base``;
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
from typing import Any

import cv2
import numpy as np

from gemini335 import Gemini335Camera
from perception import DetectorConfig, annotate, detect_blue_cylinder


JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


class SafetyError(RuntimeError):
    """Raised when a physical-motion precondition or runtime check fails."""


@dataclass(frozen=True)
class PickPlan:
    target_camera_m: tuple[float, float, float]
    target_base_m: tuple[float, float, float]
    grasp_base_m: tuple[float, float, float]
    overhead_base_m: tuple[float, float, float]
    lift_base_m: tuple[float, float, float]
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
        "camera_to_base_4x4",
        "right_shoulder_position_base_m",
        "kinematics",
        "motion",
        "joint_limits_deg",
        "gripper",
        "workspace_base_m",
        "safe_home_joints_deg",
    }
    missing = required - config.keys()
    if missing:
        raise ValueError(f"Missing config fields: {sorted(missing)}")
    matrix = np.asarray(config["camera_to_base_4x4"], dtype=np.float64)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("camera_to_base_4x4 must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8):
        raise ValueError("camera_to_base_4x4 last row must be [0, 0, 0, 1]")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=2e-2):
        raise ValueError("camera_to_base rotation is not orthonormal")
    _vector3(config["right_shoulder_position_base_m"], "right_shoulder_position_base_m")
    return config


def transform_point(matrix_4x4: np.ndarray, point_xyz: np.ndarray) -> np.ndarray:
    homogeneous = np.append(_vector3(point_xyz, "point_xyz"), 1.0)
    return (np.asarray(matrix_4x4, dtype=np.float64) @ homogeneous)[:3]


def official_planar_ik(x_m: float, z_m: float, l1_m: float, l2_m: float) -> tuple[float, float]:
    """SO100/SO101 two-link IK used by the official XLeRobot EE example.

    Returns calibrated LeRobot motor coordinates in degrees for
    ``shoulder_lift`` and ``elbow_flex``.
    """
    radius = math.hypot(x_m, z_m)
    lower = abs(l1_m - l2_m) + 1e-4
    upper = l1_m + l2_m - 1e-4
    if not lower <= radius <= upper:
        raise SafetyError(
            f"Planar wrist target is unreachable: radius={radius:.4f} m, "
            f"allowed=[{lower:.4f}, {upper:.4f}] m"
        )
    theta1_offset = math.atan2(0.028, 0.11257)
    theta2_offset = math.atan2(0.0052, 0.1349) + theta1_offset
    cos_theta2 = -(radius**2 - l1_m**2 - l2_m**2) / (2.0 * l1_m * l2_m)
    cos_theta2 = float(np.clip(cos_theta2, -1.0, 1.0))
    theta2 = math.pi - math.acos(cos_theta2)
    theta1 = math.atan2(z_m, x_m) + math.atan2(
        l2_m * math.sin(theta2), l1_m + l2_m * math.cos(theta2)
    )
    joint2_deg = 90.0 - math.degrees(theta1 + theta1_offset)
    joint3_deg = math.degrees(theta2 + theta2_offset) - 90.0
    return joint2_deg, joint3_deg


def cartesian_to_joints(point_base_m: np.ndarray, config: dict) -> dict[str, float]:
    """Convert a grasp-center target in robot base coordinates to motor degrees."""
    shoulder = _vector3(config["right_shoulder_position_base_m"], "right shoulder")
    relative = _vector3(point_base_m, "point_base_m") - shoulder
    kin = config["kinematics"]
    forward_sign = float(kin.get("base_forward_sign", 1.0))
    lateral_sign = float(kin.get("base_lateral_sign", 1.0))
    dx = forward_sign * relative[0]
    dy = lateral_sign * relative[1]
    radial = math.hypot(dx, dy)
    pan = (
        float(kin.get("shoulder_pan_sign", 1.0)) * math.degrees(math.atan2(dy, dx))
        + float(kin.get("shoulder_pan_offset_deg", 0.0))
    )

    # Fixed-pitch side grasp: the jaw center is tool_length beyond the two-link wrist.
    wrist_x = radial - float(kin["tool_length_m"])
    wrist_z = float(relative[2]) - float(kin.get("shoulder_height_correction_m", 0.0))
    shoulder_lift, elbow_flex = official_planar_ik(
        wrist_x, wrist_z, float(kin["upper_arm_m"]), float(kin["lower_arm_m"])
    )
    wrist_flex = (
        -shoulder_lift
        - elbow_flex
        + float(kin.get("wrist_pitch_offset_deg", 0.0))
    )
    joints = {
        "shoulder_pan": pan,
        "shoulder_lift": shoulder_lift,
        "elbow_flex": elbow_flex,
        "wrist_flex": wrist_flex,
        "wrist_roll": float(kin.get("wrist_roll_deg", 90.0)),
    }
    for name, offset in config.get("joint_command_offsets_deg", {}).items():
        if name in joints:
            joints[name] += float(offset)
    validate_joint_targets(joints, config)
    return joints


def validate_joint_targets(targets: dict[str, float], config: dict) -> None:
    for name, value in targets.items():
        if not math.isfinite(float(value)):
            raise SafetyError(f"Non-finite joint target: {name}={value}")
        if name not in config["joint_limits_deg"]:
            raise SafetyError(f"No configured safety limit for joint {name}")
        low, high = map(float, config["joint_limits_deg"][name])
        if not low <= float(value) <= high:
            raise SafetyError(f"{name}={value:.2f} deg outside configured [{low}, {high}]")


def build_plan(target_camera_m: np.ndarray, spread_m: float, samples: int, config: dict) -> PickPlan:
    matrix = np.asarray(config["camera_to_base_4x4"], dtype=np.float64)
    target_base = transform_point(matrix, target_camera_m)
    workspace = config["workspace_base_m"]
    for index, axis in enumerate("xyz"):
        low, high = map(float, workspace[axis])
        if not low <= target_base[index] <= high:
            raise SafetyError(
                f"Detected target {axis}={target_base[index]:.4f} m is outside workspace [{low}, {high}]"
            )

    motion = config["motion"]
    grasp = target_base + _vector3(motion.get("grasp_offset_base_m", [0, 0, 0]), "grasp offset")
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
        target_camera_m=tuple(map(float, target_camera_m)),
        target_base_m=tuple(map(float, target_base)),
        grasp_base_m=tuple(map(float, grasp)),
        overhead_base_m=tuple(map(float, overhead)),
        lift_base_m=tuple(map(float, lift)),
        overhead_joints_deg=overhead_joints,
        grasp_joints_deg=grasp_joints,
        lift_joints_deg=lift_joints,
        centroid_spread_m=float(spread_m),
        samples=int(samples),
    )


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
            samples.append(np.asarray(detection.cylinder_center_estimate_m, dtype=np.float64))
            print(
                f"[PERCEPTION {len(samples):02d}/{args.samples}] "
                f"camera_xyz={np.round(samples[-1], 4).tolist()} conf={detection.confidence:.2f}"
            )
        if not args.no_preview:
            view = annotate(bgr, mask, detection, intrinsics)
            cv2.imshow("XLeRobot real pick acquisition | ESC abort", view)
            if cv2.waitKey(1) & 0xFF == 27:
                raise KeyboardInterrupt

    if len(samples) < args.samples:
        raise SafetyError(f"Perception timeout: received {len(samples)}/{args.samples} valid detections")
    stacked = np.stack(samples)
    target = np.median(stacked, axis=0)
    spread = float(np.max(np.linalg.norm(stacked - target, axis=1)))
    if spread > args.max_spread:
        raise SafetyError(f"Unstable centroid: max spread {spread:.4f} m > {args.max_spread:.4f} m")

    if last_bgr is not None:
        cv2.imwrite(str(output_dir / "acquisition_rgb.png"), last_bgr)
        cv2.imwrite(str(output_dir / "acquisition_mask.png"), last_mask)
        cv2.imwrite(
            str(output_dir / "acquisition_annotated.png"),
            annotate(last_bgr, last_mask, last_detection, intrinsics),
        )
        np.save(output_dir / "acquisition_depth_m.npy", last_depth)
    print(f"[PERCEPTION] stable camera centroid={target.tolist()}, max_spread={spread:.5f} m")
    return target, spread


def import_robot_classes():
    attempts = []
    candidates = (
        (
            "lerobot.robots.so_follower.so_follower",
            "lerobot.robots.so_follower.config_so_follower",
            "SO100Follower",
            "SO100FollowerConfig",
        ),
        (
            "lerobot.robots.so101_follower.so101_follower",
            "lerobot.robots.so101_follower.config_so101_follower",
            "SO101Follower",
            "SO101FollowerConfig",
        ),
        (
            "lerobot.robots.so101_follower",
            "lerobot.robots.so101_follower",
            "SO101Follower",
            "SO101FollowerConfig",
        ),
        (
            "lerobot.robots.so100_follower",
            "lerobot.robots.so100_follower",
            "SO100Follower",
            "SO100FollowerConfig",
        ),
    )
    for robot_module, config_module, robot_name, config_name in candidates:
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


def execute_trajectory(robot, target: dict[str, float], duration_s: float, config: dict, phase: str) -> None:
    validate_joint_targets(target, config)
    start = read_joint_positions(robot)
    frequency = float(config["motion"]["control_hz"])
    steps = max(2, int(duration_s * frequency))
    max_step = float(config["motion"]["max_command_step_deg"])
    max_tracking_error = float(config["motion"]["max_tracking_error_deg"])
    previous = start.copy()
    print(f"[PHASE] {phase}: duration={duration_s:.1f}s target={target}")
    for step in range(1, steps + 1):
        alpha = smoothstep(step / steps)
        command = {}
        for name in JOINTS:
            desired = start[name] + alpha * (float(target[name]) - start[name])
            delta = desired - previous[name]
            if abs(delta) > max_step + 1e-9:
                raise SafetyError(f"{phase}: {name} step {delta:.2f} deg exceeds {max_step:.2f}")
            command[f"{name}.pos"] = desired
            previous[name] = desired
        robot.send_action(command)
        if step > max(2, int(0.5 * frequency)) and step % max(1, int(frequency / 5)) == 0:
            measured = read_joint_positions(robot)
            error = max(abs(measured[name] - previous[name]) for name in JOINTS)
            if error > max_tracking_error:
                raise SafetyError(
                    f"{phase}: tracking error {error:.1f} deg exceeds {max_tracking_error:.1f}; aborting"
                )
        time.sleep(1.0 / frequency)


def execute_cartesian_trajectory(
    robot,
    start_base_m: tuple[float, float, float],
    target_base_m: tuple[float, float, float],
    gripper_deg: float,
    duration_s: float,
    config: dict,
    phase: str,
) -> None:
    """Follow a Cartesian line, solving IK at every control cycle."""
    start_xyz = _vector3(start_base_m, "Cartesian start")
    target_xyz = _vector3(target_base_m, "Cartesian target")
    frequency = float(config["motion"]["control_hz"])
    steps = max(2, int(duration_s * frequency))
    max_step = float(config["motion"]["max_command_step_deg"])
    max_tracking_error = float(config["motion"]["max_tracking_error_deg"])
    previous = read_joint_positions(robot)
    print(
        f"[PHASE] {phase}: Cartesian {start_xyz.tolist()} -> {target_xyz.tolist()}, "
        f"duration={duration_s:.1f}s"
    )
    for step in range(1, steps + 1):
        alpha = smoothstep(step / steps)
        xyz = start_xyz + alpha * (target_xyz - start_xyz)
        desired = cartesian_to_joints(xyz, config)
        desired["gripper"] = float(gripper_deg)
        validate_joint_targets(desired, config)
        command = {}
        for name in JOINTS:
            delta = desired[name] - previous[name]
            if abs(delta) > max_step + 1e-9:
                raise SafetyError(f"{phase}: {name} step {delta:.2f} deg exceeds {max_step:.2f}")
            command[f"{name}.pos"] = desired[name]
            previous[name] = desired[name]
        robot.send_action(command)
        if step > max(2, int(0.5 * frequency)) and step % max(1, int(frequency / 5)) == 0:
            measured = read_joint_positions(robot)
            error = max(abs(measured[name] - previous[name]) for name in JOINTS)
            if error > max_tracking_error:
                raise SafetyError(
                    f"{phase}: tracking error {error:.1f} deg exceeds {max_tracking_error:.1f}; aborting"
                )
        time.sleep(1.0 / frequency)


def inspect_robot(port: str, robot_id: str) -> None:
    if not port:
        raise SafetyError("--port is required with --inspect-robot")
    robot = make_robot(port, robot_id)
    connected = False
    try:
        connect_without_calibration(robot)
        connected = True
        print(json.dumps(read_joint_positions(robot), indent=2))
        print("[INSPECT] read-only inspection completed; no send_action call was made")
    finally:
        if connected:
            robot.disconnect()


def execute_pick(plan: PickPlan, config: dict, port: str, robot_id: str) -> None:
    if not config["calibrated"]:
        raise SafetyError("Config calibrated=false; physical motion is locked")
    if not port:
        raise SafetyError("--port is required with --execute")
    robot = make_robot(port, robot_id)
    connected = False
    try:
        connect_without_calibration(robot)
        connected = True
        start = read_joint_positions(robot)
        print(f"[ROBOT] connected; measured joints={start}")
        validate_joint_targets(start, config)
        home = config["safe_home_joints_deg"]
        arm_joint_names = JOINTS[:-1]
        if any(home.get(name) is None for name in arm_joint_names):
            raise SafetyError("safe_home_joints_deg must be measured and filled before execution")
        home_error = max(abs(start[name] - float(home[name])) for name in arm_joint_names)
        home_tolerance = float(config["motion"]["home_tolerance_deg"])
        if home_error > home_tolerance:
            raise SafetyError(
                f"Robot is not in the calibrated safe home pose: max error={home_error:.1f} deg "
                f"> {home_tolerance:.1f} deg"
            )
        answer = input(
            "Remove people/obstacles, hold the emergency stop, verify the arm is in a safe home pose. "
            "Type PICK to move: "
        ).strip()
        if answer != "PICK":
            raise SafetyError("Operator did not confirm PICK")

        durations = config["motion"]["phase_duration_s"]
        overhead = dict(plan.overhead_joints_deg)
        grasp = dict(plan.grasp_joints_deg)
        lift = dict(plan.lift_joints_deg)
        open_value = float(config["gripper"]["open_deg"])
        closed_value = float(config["gripper"]["closed_deg"])
        overhead["gripper"] = open_value
        grasp["gripper"] = open_value
        lift["gripper"] = closed_value

        open_pose = start | {"gripper": open_value}
        execute_trajectory(robot, open_pose, float(durations["open"]), config, "open")
        execute_trajectory(robot, overhead, float(durations["transit"]), config, "transit")
        execute_cartesian_trajectory(
            robot, plan.overhead_base_m, plan.grasp_base_m, open_value,
            float(durations["approach"]), config, "approach"
        )
        closed_pose = grasp | {"gripper": closed_value}
        execute_trajectory(robot, closed_pose, float(durations["close"]), config, "close")
        execute_cartesian_trajectory(
            robot, plan.grasp_base_m, plan.lift_base_m, closed_value,
            float(durations["lift"]), config, "lift"
        )
        print(f"[HOLD] holding lifted target for {durations['hold']:.1f}s")
        time.sleep(float(durations["hold"]))
        print("[RESULT] motion sequence completed; object retention is not force-verified")
    finally:
        if connected:
            robot.disconnect()
            print("[ROBOT] disconnected; verify whether your motor model releases torque on disconnect")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("pick_config.example.json"),
        help="robot calibration JSON; default template permits dry-run only",
    )
    parser.add_argument("--port", default=None, help="right-arm USB port, e.g. /dev/arm_right or COM5")
    parser.add_argument("--robot-id", default="xlerobot_right_arm")
    parser.add_argument("--execute", action="store_true", help="enable physical motion after all checks")
    parser.add_argument(
        "--inspect-robot", action="store_true", help="connect, print joint positions, disconnect; send no action"
    )
    parser.add_argument("--samples", type=int, default=15)
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
    if not args.config.exists():
        example = Path(__file__).with_name("pick_config.example.json")
        print(f"[ERROR] Missing {args.config}. Copy and calibrate {example} first.", file=sys.stderr)
        return 2
    output = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    output.mkdir(parents=True, exist_ok=True)
    camera = Gemini335Camera()
    try:
        config = load_config(args.config)
        if args.inspect_robot:
            inspect_robot(args.port, args.robot_id)
            return 0
        if args.execute and not config["calibrated"]:
            raise SafetyError("Config calibrated=false; refusing to acquire or move in execute mode")
        target_camera, spread = acquire_stable_target(camera, args, output)
        plan = build_plan(target_camera, spread, args.samples, config)
        plan_path = output / "pick_plan.json"
        plan_path.write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
        print(json.dumps(asdict(plan), indent=2))
        print(f"[PLAN] saved {plan_path}")
        camera.stop()
        cv2.destroyAllWindows()
        if not args.execute:
            print("[DRY-RUN] no motor connection or command was made. Add --execute only after calibration review.")
            return 0
        execute_pick(plan, config, args.port, args.robot_id)
        return 0
    except KeyboardInterrupt:
        print("\n[ABORT] operator interrupt")
        return 130
    except (SafetyError, RuntimeError, ValueError) as exc:
        print(f"[ABORT] {exc}", file=sys.stderr)
        return 2
    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
