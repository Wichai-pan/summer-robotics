# Copyright (c) 2026, XLeRobot Project Developers.
# SPDX-License-Identifier: BSD-3-Clause

"""Pick the cylinder nearest to XLeRobot and lift it clear of the table.

The script is deliberately deterministic and does not depend on Nucleus assets.
It can either read candidate poses from the live USD stage or estimate them
from an RGB-D camera mounted on ``head_camera_link``.  It then plans a
pre-grasp and a straight collision-free approach, closes the real XLeRobot jaw,
and verifies that the selected cylinder follows the gripper during a lift.
"""

"""Launch Isaac Sim before importing Isaac Lab modules."""

import argparse
from pathlib import Path

from isaaclab.app import AppLauncher


parser = argparse.ArgumentParser(description="Run the deterministic XLeRobot cylinder pick task.")
parser.add_argument("--usd_path", type=str, default=None, help="Override the bundled XLeRobot USD path.")
parser.add_argument("--max_steps", type=int, default=2600, help="Hard simulation-step timeout.")
parser.add_argument(
    "--stall_timeout",
    type=float,
    default=240.0,
    metavar="SECONDS",
    help="Dump Python stacks and terminate if no simulation step completes for this long; 0 disables.",
)
parser.add_argument(
    "--target_source",
    choices=("stage", "rgbd"),
    default="stage",
    help="Acquire candidate poses from USD stage truth or the head RGB-D sensor.",
)
parser.add_argument(
    "--save_rgbd_debug",
    type=str,
    default=None,
    metavar="DIR",
    help="In RGB-D mode, save the acquisition RGB, depth visualization, and color masks.",
)
parser.add_argument(
    "--validate_rgbd_ground_truth",
    action="store_true",
    help="Log RGB-D position error against simulation truth; never use truth for planning.",
)
parser.add_argument(
    "--keep_open",
    action="store_true",
    help="Keep stepping after success/failure for interactive inspection.",
)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()
if args_cli.target_source == "rgbd" and not args_cli.enable_cameras:
    args_cli.enable_cameras = True
    print("[SETUP] RGB-D target mode: enabling camera rendering automatically.")

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

"""The rest of the imports require the running simulator."""

import faulthandler
import json
import math
import os
import sys
import threading
import time

import torch
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

import isaaclab.sim as sim_utils
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.controllers import DifferentialIKController, DifferentialIKControllerCfg
from isaaclab.scene import InteractiveScene, InteractiveSceneCfg
from isaaclab.sensors import CameraCfg
from isaaclab.utils import configclass
from isaaclab.utils.math import matrix_from_quat, quat_apply, subtract_frame_transforms

from rgbd_cylinder_perception import CylinderDetection, estimate_colored_cylinders, select_nearest_detection


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USD_PATH = PROJECT_ROOT / "xlerobot" / "xlerobot" / "xlerobot.usd"
XLEROBOT_USD_PATH = Path(args_cli.usd_path).resolve() if args_cli.usd_path else DEFAULT_USD_PATH.resolve()

# Scene dimensions and poses, in SI units.  The worktable is directly in front
# of the chassis.  Its near edge leaves clearance for the chassis while the
# blue cylinder sits close enough to remain inside the right arm workspace.
TABLE_SIZE = (0.38, 0.42, 0.04)
TABLE_POS = (0.400, 0.00, 0.76)
CYLINDER_RADIUS = 0.018
CYLINDER_HEIGHT = 0.080
NEAR_CYLINDER_POS = (0.280, -0.04, 0.82)
FAR_CYLINDER_POS = (0.440, 0.08, 0.82)
CYLINDER_MASS = 0.025

# Head RGB-D mounting calibration.  The parent pose comes from the unmodified
# XLeRobot URDF and the camera offset/orientation is fixed relative to
# head_camera_link.  RGB-D points are transformed with these known extrinsics,
# never with a target prim or target rigid-body world pose.
# Keep the articulated head at its calibration zero.  Isaac Sim's RTX camera
# remains rigidly authored beneath head_camera_link; the camera's own mounting
# rotation below points it at the front worktable.
HEAD_PAN_POSITION = 0.0
HEAD_TILT_POSITION = 0.0
HEAD_CAMERA_OFFSET = (0.10, 0.0, -0.025)
# OpenGL camera axes, aimed at the front worktable near (0.36, 0.00, 0.82).
HEAD_CAMERA_OPENGL_QUAT = (0.65204327, 0.27356823, -0.27356823, -0.65204327)
HEAD_CAMERA_WIDTH = 640
HEAD_CAMERA_HEIGHT = 480
HEAD_CAMERA_FOCAL_LENGTH = 24.0
HEAD_CAMERA_HORIZONTAL_APERTURE = 20.955
RGBD_ACQUISITION_DEADLINE = 400

# The complete task has exactly four motion phases and no hidden waypoints.
INITIALIZATION_STEPS = 100
TRANSIT_STEPS = 500
APPROACH_STEPS = 550
CLOSE_STEPS = 300
LIFT_STEPS = 500
LIFT_VALIDATION_STEPS = 200
WRIST_ROLL_GRASP_POSITION = math.pi / 2.0
# Folded-upright home pose.  It shares the final grasp orientation, so transit
# can be one direct Cartesian segment without a wrist flip or an IK branch
# change.  Order: Rotation, Pitch, Elbow, Wrist_Pitch.
INITIAL_ARM_JOINT_POSITIONS = (-0.306, 2.307, 1.811, 0.496)

RIGHT_ARM_JOINT_NAMES = ["Rotation", "Pitch", "Elbow", "Wrist_Pitch", "Wrist_Roll"]
RIGHT_ARM_IK_JOINT_NAMES = ["Rotation", "Pitch", "Elbow", "Wrist_Pitch"]
RIGHT_ARM_EE_BODY_NAME = "Fixed_Jaw"
RIGHT_GRIPPER_JOINT_NAME = "Jaw"
LEFT_ARM_JOINT_NAMES = ["Rotation_2", "Pitch_2", "Elbow_2", "Wrist_Pitch_2", "Wrist_Roll_2"]
LEFT_ARM_EE_BODY_NAME = "Fixed_Jaw_2"
# Mirror the right home about the robot centerline.  The pitch-chain angles and
# positive wrist roll stay equal; only the shoulder rotation changes sign.
PARKED_LEFT_ARM_JOINT_POSITIONS = (0.306, 2.307, 1.811, 0.496)

# Midpoints of the two fingertip reference frames, expressed in the Fixed_Jaw
# frame and derived from the unmodified robot URDF.  At 0.40 rad the tip gap is
# 35.8 mm, matching the 36 mm cylinder diameter without visual interpenetration.
OPEN_JAW_POSITION = 0.85
CLOSED_JAW_POSITION = 0.40
OPEN_GRASP_CENTER_OFFSET_EE = (-0.02358, -0.09257, 0.0)
CONTACT_GRASP_CENTER_OFFSET_EE = (-0.00788, -0.09744, 0.0)
GRIPPER_CAMERA_OFFSET_EE = (0.0, -0.020, 0.050)
# Local collision envelopes derived from the unmodified URDF mesh bounds.
# Camera bounds include its fixed-joint and visual transforms in Fixed_Jaw.
ARM_COLLISION_ENVELOPES = {
    "Lower_Arm": ((-0.0352, -0.0151, -0.0121), (0.0262, 0.0220, 0.1452)),
    "Wrist_Pitch_Roll": ((-0.0353, -0.0627, -0.0161), (0.0282, 0.0121, 0.0161)),
    "Fixed_Jaw": ((-0.0305, -0.1065, -0.0241), (0.0372, 0.0001, 0.0241)),
    "Moving_Jaw": ((-0.0124, -0.0819, -0.0240), (0.0082, 0.0094, 0.0240)),
}
CAMERA_ENVELOPE_EE = ((-0.0219, -0.0283, 0.0222), (0.0145, 0.0147, 0.0897))
# Chassis collision boxes from xlerobot.urdf, expressed in the fixed root frame.
CHASSIS_COLLISION_BOXES = (
    ((-0.1575, -0.2025, 0.1000), (0.1575, 0.2025, 0.6900)),
    ((0.1485, -0.2025, 0.6850), (0.1575, 0.2025, 0.7750)),
    ((-0.1575, -0.2025, 0.6850), (-0.1485, 0.2025, 0.7750)),
    ((-0.1575, 0.1935, 0.6850), (0.1575, 0.2025, 0.7750)),
    ((-0.1575, -0.2025, 0.6850), (0.1575, -0.1935, 0.7750)),
)
MIN_GEOMETRY_CLEARANCE = 0.0
COLLISION_CHECK_INTERVAL = 10
TRANSIT_GOAL_TOLERANCE = 0.040
APPROACH_GOAL_TOLERANCE = 0.015
GRASP_ATTACH_JAW_POSITION = 0.43
GRASP_MAX_XY_ERROR = 0.025
GRASP_SIDEWALL_END_MARGIN = 0.005
GRASP_PAD_CONTACT_Z_OFFSET = -0.020
# Put the cylinder 12 mm behind the nominal open-jaw midpoint, toward the
# wrist, so both sloped tips pass around it before the pads close.
GRASP_DEPTH_OFFSET = 0.012
GRASP_HEIGHT_OFFSET = 0.020
SAFE_TRANSIT_HEIGHT = 0.950
LIFT_DISTANCE = 0.13


XLEROBOT_CFG = ArticulationCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=XLEROBOT_USD_PATH.as_posix(),
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            disable_gravity=False,
            max_depenetration_velocity=3.0,
        ),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            fix_root_link=True,
            enabled_self_collisions=False,
            solver_position_iteration_count=16,
            solver_velocity_iteration_count=4,
        ),
    ),
    init_state=ArticulationCfg.InitialStateCfg(
        pos=(0.0, 0.0, 0.0),
        joint_pos={
            "root_x_axis_joint": 0.0,
            "root_y_axis_joint": 0.0,
            "root_z_rotation_joint": 0.0,
            "Rotation": INITIAL_ARM_JOINT_POSITIONS[0],
            "Pitch": INITIAL_ARM_JOINT_POSITIONS[1],
            "Elbow": INITIAL_ARM_JOINT_POSITIONS[2],
            "Wrist_Pitch": INITIAL_ARM_JOINT_POSITIONS[3],
            # +90 degrees keeps the jaw opening horizontal and flips the wrist
            # camera above the gripper instead of below it.
            "Wrist_Roll": WRIST_ROLL_GRASP_POSITION,
            "Jaw": OPEN_JAW_POSITION,
            "Rotation_2": PARKED_LEFT_ARM_JOINT_POSITIONS[0],
            "Pitch_2": PARKED_LEFT_ARM_JOINT_POSITIONS[1],
            "Elbow_2": PARKED_LEFT_ARM_JOINT_POSITIONS[2],
            "Wrist_Pitch_2": PARKED_LEFT_ARM_JOINT_POSITIONS[3],
            "Wrist_Roll_2": WRIST_ROLL_GRASP_POSITION,
            "Jaw_2": 0.0,
            "head_pan_joint": HEAD_PAN_POSITION,
            "head_tilt_joint": HEAD_TILT_POSITION,
        },
    ),
    actuators={
        "base": ImplicitActuatorCfg(
            joint_names_expr=["root_.*"],
            effort_limit_sim=1000.0,
            velocity_limit_sim=2.0,
            stiffness=10000.0,
            damping=1000.0,
        ),
        "right_arm": ImplicitActuatorCfg(
            joint_names_expr=RIGHT_ARM_JOINT_NAMES,
            effort_limit_sim=90.0,
            velocity_limit_sim=2.5,
            stiffness=900.0,
            damping=90.0,
        ),
        "left_arm": ImplicitActuatorCfg(
            joint_names_expr=["Rotation_2", "Pitch_2", "Elbow_2", "Wrist_Pitch_2", "Wrist_Roll_2"],
            effort_limit_sim=80.0,
            velocity_limit_sim=2.5,
            stiffness=800.0,
            damping=80.0,
        ),
        "grippers_and_head": ImplicitActuatorCfg(
            joint_names_expr=["Jaw", "Jaw_2", "head_pan_joint", "head_tilt_joint"],
            effort_limit_sim=8.0,
            velocity_limit_sim=1.2,
            stiffness=120.0,
            damping=10.0,
        ),
    },
)


CYLINDER_SPAWN_CFG = sim_utils.CylinderCfg(
    radius=CYLINDER_RADIUS,
    height=CYLINDER_HEIGHT,
    rigid_props=sim_utils.RigidBodyPropertiesCfg(
        disable_gravity=False,
        max_depenetration_velocity=1.0,
        solver_position_iteration_count=16,
        solver_velocity_iteration_count=4,
    ),
    collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0.003, rest_offset=0.0),
    mass_props=sim_utils.MassPropertiesCfg(mass=CYLINDER_MASS),
    physics_material=sim_utils.RigidBodyMaterialCfg(
        static_friction=1.6,
        dynamic_friction=1.3,
        restitution=0.0,
    ),
)


@configclass
class PickSceneCfg(InteractiveSceneCfg):
    """One local, deterministic pick scene."""

    table = AssetBaseCfg(
        prim_path="/World/Table",
        spawn=sim_utils.CuboidCfg(
            size=TABLE_SIZE,
            collision_props=sim_utils.CollisionPropertiesCfg(),
            physics_material=sim_utils.RigidBodyMaterialCfg(
                static_friction=1.1,
                dynamic_friction=0.9,
                restitution=0.0,
            ),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.55, 0.36, 0.20)),
        ),
        init_state=AssetBaseCfg.InitialStateCfg(pos=TABLE_POS),
    )
    near_cylinder = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/NearCylinder",
        spawn=CYLINDER_SPAWN_CFG.replace(
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.05, 0.2, 0.9))
        ),
        init_state=RigidObjectCfg.InitialStateCfg(pos=NEAR_CYLINDER_POS),
    )
    far_cylinder = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/FarCylinder",
        spawn=CYLINDER_SPAWN_CFG.replace(
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.9, 0.05, 0.05))
        ),
        init_state=RigidObjectCfg.InitialStateCfg(pos=FAR_CYLINDER_POS),
    )
    robot: ArticulationCfg = XLEROBOT_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
    if args_cli.target_source == "rgbd":
        head_camera = CameraCfg(
            prim_path="{ENV_REGEX_NS}/Robot/head_tilt_link/head_camera_link/Head_RGBD_Camera",
            update_period=0.0,
            width=HEAD_CAMERA_WIDTH,
            height=HEAD_CAMERA_HEIGHT,
            data_types=["rgb", "distance_to_image_plane"],
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=HEAD_CAMERA_FOCAL_LENGTH,
                focus_distance=1.0,
                horizontal_aperture=HEAD_CAMERA_HORIZONTAL_APERTURE,
                clipping_range=(0.10, 2.0),
            ),
            offset=CameraCfg.OffsetCfg(
                pos=HEAD_CAMERA_OFFSET,
                rot=HEAD_CAMERA_OPENGL_QUAT,
                convention="opengl",
            ),
            update_latest_camera_pose=True,
        )
    dome_light = AssetBaseCfg(
        prim_path="/World/Light",
        spawn=sim_utils.DomeLightCfg(intensity=2500.0, color=(0.8, 0.8, 0.8)),
    )


def _stage_world_pose(stage: Usd.Stage, prim_path: str) -> tuple[list[float], list[float]]:
    """Read a prim pose directly from the live USD stage."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Missing stage prim: {prim_path}")
    matrix = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(prim)
    translation = matrix.ExtractTranslation()
    rotation = matrix.ExtractRotationQuat()
    imag = rotation.GetImaginary()
    return (
        [float(translation[0]), float(translation[1]), float(translation[2])],
        [float(rotation.GetReal()), float(imag[0]), float(imag[1]), float(imag[2])],
    )


def _create_preserving_fixed_joint(
    stage: Usd.Stage,
    joint_path: str,
    body0_path: str,
    body1_path: str,
    body1_pos_in_body0: list[float],
    body1_quat_in_body0: list[float],
) -> UsdPhysics.FixedJoint:
    """Attach two bodies without snapping either one to the other's origin."""
    joint = UsdPhysics.FixedJoint.Define(stage, joint_path)
    joint.GetBody0Rel().SetTargets([Sdf.Path(body0_path)])
    joint.GetBody1Rel().SetTargets([Sdf.Path(body1_path)])
    joint.CreateLocalPos0Attr(Gf.Vec3f(*body1_pos_in_body0))
    joint.CreateLocalPos1Attr(Gf.Vec3f(0.0))
    joint.CreateLocalRot0Attr(
        Gf.Quatf(body1_quat_in_body0[0], Gf.Vec3f(*body1_quat_in_body0[1:4]))
    )
    joint.CreateLocalRot1Attr(Gf.Quatf(1.0))
    return joint


def _resolve_robot_indices(robot):
    arm_joint_ids, arm_joint_names = robot.find_joints(RIGHT_ARM_JOINT_NAMES, preserve_order=True)
    ik_joint_ids, ik_joint_names = robot.find_joints(RIGHT_ARM_IK_JOINT_NAMES, preserve_order=True)
    wrist_roll_ids, _ = robot.find_joints("Wrist_Roll", preserve_order=True)
    jaw_joint_ids, jaw_joint_names = robot.find_joints(RIGHT_GRIPPER_JOINT_NAME, preserve_order=True)
    ee_body_ids, ee_body_names = robot.find_bodies(RIGHT_ARM_EE_BODY_NAME, preserve_order=True)
    if len(arm_joint_ids) != len(RIGHT_ARM_JOINT_NAMES):
        raise RuntimeError(f"Could not resolve right arm joints: {arm_joint_names}")
    if len(jaw_joint_ids) != 1 or len(ee_body_ids) != 1:
        raise RuntimeError(
            f"Could not resolve gripper/EE. jaw={jaw_joint_names}, ee={ee_body_names}, bodies={robot.body_names}"
        )
    collision_body_ids = {}
    for body_name in ARM_COLLISION_ENVELOPES:
        body_ids, body_names = robot.find_bodies(body_name, preserve_order=True)
        if len(body_ids) != 1:
            raise RuntimeError(f"Could not resolve collision-check body {body_name}: {body_names}")
        collision_body_ids[body_name] = body_ids[0]
    print(
        f"[SETUP] arm joints={arm_joint_names}; IK joints={ik_joint_names}; "
        f"jaw={jaw_joint_names[0]}; ee={ee_body_names[0]}; "
        f"collision_bodies={list(collision_body_ids)}"
    )
    return (
        arm_joint_ids,
        ik_joint_ids,
        wrist_roll_ids[0],
        jaw_joint_ids[0],
        ee_body_ids[0],
        collision_body_ids,
    )


def _phase_alpha(step: int, start: int, duration: int) -> float:
    """Cubic smooth-step interpolation with zero endpoint velocity."""
    value = min(max((step - start) / max(duration, 1), 0.0), 1.0)
    return value * value * (3.0 - 2.0 * value)


def _grasp_center_offset(jaw_position: float, device: str) -> torch.Tensor:
    """Interpolate the fingertip midpoint as the curved moving jaw closes."""
    close_fraction = (OPEN_JAW_POSITION - jaw_position) / (OPEN_JAW_POSITION - CLOSED_JAW_POSITION)
    close_fraction = min(max(close_fraction, 0.0), 1.0)
    open_offset = torch.tensor([OPEN_GRASP_CENTER_OFFSET_EE], device=device)
    contact_offset = torch.tensor([CONTACT_GRASP_CENTER_OFFSET_EE], device=device)
    return open_offset + close_fraction * (contact_offset - open_offset)


def _box_corners(bounds, device: str) -> torch.Tensor:
    """Return the eight corners of a local axis-aligned box."""
    lower, upper = bounds
    return torch.tensor(
        [
            [x, y, z]
            for x in (lower[0], upper[0])
            for y in (lower[1], upper[1])
            for z in (lower[2], upper[2])
        ],
        device=device,
    )


def _world_aabb(position: torch.Tensor, orientation: torch.Tensor, bounds, device: str):
    """Transform a local mesh envelope and return its conservative world AABB."""
    corners = _box_corners(bounds, device)
    quaternions = orientation.unsqueeze(0).expand(corners.shape[0], -1)
    world_corners = position.unsqueeze(0) + quat_apply(quaternions, corners)
    return torch.amin(world_corners, dim=0), torch.amax(world_corners, dim=0)


def _world_obb(position: torch.Tensor, orientation: torch.Tensor, bounds, device: str):
    """Transform a local mesh envelope without losing its orientation."""
    lower = torch.tensor(bounds[0], device=device)
    upper = torch.tensor(bounds[1], device=device)
    local_center = 0.5 * (lower + upper)
    half_extents = 0.5 * (upper - lower)
    center = position + quat_apply(orientation.unsqueeze(0), local_center.unsqueeze(0))[0]
    axes = matrix_from_quat(orientation.unsqueeze(0))[0]
    return center, axes, half_extents


def _signed_obb_clearance(first, second) -> float:
    """SAT clearance for two oriented boxes; negative means actual box overlap."""
    first_center, first_axes, first_half = first
    second_center, second_axes, second_half = second
    rotation = first_axes.transpose(0, 1) @ second_axes
    abs_rotation = torch.abs(rotation) + 1.0e-7
    translation = first_axes.transpose(0, 1) @ (second_center - first_center)
    separations = []

    for axis in range(3):
        radius_first = first_half[axis]
        radius_second = torch.dot(second_half, abs_rotation[axis, :])
        separations.append(torch.abs(translation[axis]) - radius_first - radius_second)
    for axis in range(3):
        radius_first = torch.dot(first_half, abs_rotation[:, axis])
        radius_second = second_half[axis]
        projection = torch.abs(torch.dot(translation, rotation[:, axis]))
        separations.append(projection - radius_first - radius_second)

    # The nine edge cross-product axes complete the OBB separating-axis test.
    # Normalize their separation values so the logged clearance remains metric.
    for first_axis in range(3):
        first_next = (first_axis + 1) % 3
        first_last = (first_axis + 2) % 3
        for second_axis in range(3):
            radius_first = (
                first_half[first_next] * abs_rotation[first_last, second_axis]
                + first_half[first_last] * abs_rotation[first_next, second_axis]
            )
            radius_second = (
                second_half[(second_axis + 1) % 3]
                * abs_rotation[first_axis, (second_axis + 2) % 3]
                + second_half[(second_axis + 2) % 3]
                * abs_rotation[first_axis, (second_axis + 1) % 3]
            )
            projection = torch.abs(
                translation[first_last] * rotation[first_next, second_axis]
                - translation[first_next] * rotation[first_last, second_axis]
            )
            axis_norm = torch.sqrt(torch.clamp(1.0 - rotation[first_axis, second_axis] ** 2, min=0.0))
            if float(axis_norm) > 1.0e-5:
                separations.append((projection - radius_first - radius_second) / axis_norm)
    return float(torch.amax(torch.stack(separations)))


def _geometry_clearances(
    robot,
    collision_body_ids,
    ee_body_id: int,
    device: str,
    arm_label: str = "Right",
):
    """Check distal arm mesh envelopes against chassis boxes and the table."""
    components = {}
    component_aabbs = {}
    for body_name, body_id in collision_body_ids.items():
        body_position = robot.data.body_pos_w[0, body_id]
        body_orientation = robot.data.body_quat_w[0, body_id]
        components[body_name] = _world_obb(
            body_position,
            body_orientation,
            ARM_COLLISION_ENVELOPES[body_name],
            device,
        )
        component_aabbs[body_name] = _world_aabb(
            body_position,
            body_orientation,
            ARM_COLLISION_ENVELOPES[body_name],
            device,
        )
    camera_label = f"{arm_label}_Arm_Camera"
    components[camera_label] = _world_obb(
        robot.data.body_pos_w[0, ee_body_id],
        robot.data.body_quat_w[0, ee_body_id],
        CAMERA_ENVELOPE_EE,
        device,
    )
    component_aabbs[camera_label] = _world_aabb(
        robot.data.body_pos_w[0, ee_body_id],
        robot.data.body_quat_w[0, ee_body_id],
        CAMERA_ENVELOPE_EE,
        device,
    )

    root_pos = robot.data.root_pos_w[0]
    root_quat = robot.data.root_quat_w[0]
    obstacles = {}
    for index, bounds in enumerate(CHASSIS_COLLISION_BOXES):
        obstacles[f"Chassis[{index}]"] = _world_obb(root_pos, root_quat, bounds, device)
    identity_quat = torch.tensor([1.0, 0.0, 0.0, 0.0], device=device)
    table_center = torch.tensor(TABLE_POS, device=device)
    table_half = torch.tensor(TABLE_SIZE, device=device) * 0.5
    obstacles["Table"] = _world_obb(
        table_center,
        identity_quat,
        ((-table_half).cpu().tolist(), table_half.cpu().tolist()),
        device,
    )

    clearances = {}
    for component_name, component_obb in components.items():
        for obstacle_name, obstacle_obb in obstacles.items():
            clearances[(component_name, obstacle_name)] = _signed_obb_clearance(
                component_obb,
                obstacle_obb,
            )
    return clearances, component_aabbs


def _print_phase(name: str, step: int, target: torch.Tensor | None = None) -> None:
    suffix = "" if target is None else f"; EE target={target[0].detach().cpu().tolist()}"
    print(f"[PHASE] step={step}: {name}{suffix}")


def _known_base_to_head_camera(device: str) -> tuple[torch.Tensor, torch.Tensor]:
    """Return calibrated base-to-camera position and ROS optical rotation.

    This is forward kinematics over the fixed URDF mounting dimensions at the
    commanded pan/tilt values.  It intentionally does not query the USD stage.
    """
    pan_cos, pan_sin = math.cos(HEAD_PAN_POSITION), math.sin(HEAD_PAN_POSITION)
    tilt_cos, tilt_sin = math.cos(HEAD_TILT_POSITION), math.sin(HEAD_TILT_POSITION)
    rotation_pan = torch.tensor(
        [[pan_cos, -pan_sin, 0.0], [pan_sin, pan_cos, 0.0], [0.0, 0.0, 1.0]],
        device=device,
        dtype=torch.float32,
    )
    rotation_tilt = torch.tensor(
        [[tilt_cos, 0.0, tilt_sin], [0.0, 1.0, 0.0], [-tilt_sin, 0.0, tilt_cos]],
        device=device,
        dtype=torch.float32,
    )
    rotation_head = rotation_pan @ rotation_tilt

    # base_link -> top_base -> head_pan -> head_tilt joint origins
    position = torch.tensor([-0.178, 0.0, 0.730], device=device)
    position += rotation_pan @ torch.tensor([0.031, 0.0, 0.43815], device=device)
    # head_tilt -> head_camera_link plus the authored sensor offset
    camera_from_tilt = torch.tensor([0.055, 0.0, 0.0225], device=device)
    camera_from_tilt += torch.tensor(HEAD_CAMERA_OFFSET, device=device)
    position += rotation_head @ camera_from_tilt

    local_opengl_rotation = matrix_from_quat(
        torch.tensor([HEAD_CAMERA_OPENGL_QUAT], device=device, dtype=torch.float32)
    )[0]
    # OpenGL has +X right, +Y up, -Z forward; ROS optical has +X right,
    # +Y down, +Z forward.
    opengl_from_ros = torch.diag(torch.tensor([1.0, -1.0, -1.0], device=device))
    rotation_b_ros = rotation_head @ local_opengl_rotation @ opengl_from_ros
    return position, rotation_b_ros


def _save_rgbd_debug_images(
    rgb: torch.Tensor,
    depth: torch.Tensor,
    intrinsics: torch.Tensor,
    camera_position_b: torch.Tensor,
    camera_rotation_b_ros: torch.Tensor,
    output_dir: str,
) -> None:
    """Save the exact perception input and masks for reproducibility."""
    from PIL import Image

    from rgbd_cylinder_perception import color_masks

    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    rgb_cpu = rgb[..., :3].detach().cpu()
    if rgb_cpu.dtype != torch.uint8:
        if float(rgb_cpu.max()) <= 1.5:
            rgb_cpu = rgb_cpu * 255.0
        rgb_cpu = rgb_cpu.clamp(0, 255).to(torch.uint8)
    Image.fromarray(rgb_cpu.numpy()).save(directory / "rgb.png")

    depth_cpu = depth.squeeze(-1).detach().cpu().to(torch.float32)
    valid = torch.isfinite(depth_cpu) & (depth_cpu > 0.0) & (depth_cpu < 2.0)
    visualization = torch.zeros_like(depth_cpu, dtype=torch.uint8)
    if torch.any(valid):
        valid_depth = depth_cpu[valid]
        low = torch.quantile(valid_depth, 0.02)
        high = torch.quantile(valid_depth, 0.98)
        scaled = 255.0 * (depth_cpu - low) / max(float(high - low), 1.0e-6)
        visualization[valid] = (255.0 - scaled[valid]).clamp(0, 255).to(torch.uint8)
    Image.fromarray(visualization.numpy()).save(directory / "depth.png")
    for label, mask in color_masks(rgb).items():
        Image.fromarray((mask.detach().cpu().to(torch.uint8) * 255).numpy()).save(directory / f"mask_{label}.png")
    torch.save(
        {
            "rgb": rgb.detach().cpu(),
            "depth": depth.detach().cpu(),
            "intrinsics": intrinsics.detach().cpu(),
            "camera_position_b": camera_position_b.detach().cpu(),
            "camera_rotation_b_ros": camera_rotation_b_ros.detach().cpu(),
        },
        directory / "rgbd_frame.pt",
    )
    print(f"[PERCEPTION] saved RGB-D debug images to {directory}")


class _SimulationStallWatchdog:
    """Terminate a genuinely stuck Kit step after first dumping all Python stacks."""

    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        self.last_progress = time.monotonic()
        self.step = -1
        self.phase = "startup"
        self.stop_event = threading.Event()
        self.thread = None

    def start(self) -> None:
        if self.timeout_seconds <= 0.0:
            return
        self.thread = threading.Thread(target=self._monitor, name="simulation-stall-watchdog", daemon=True)
        self.thread.start()
        print(f"[WATCHDOG] simulation stall timeout={self.timeout_seconds:.1f}s")

    def ping(self, step: int, phase: str) -> None:
        self.step = step
        self.phase = phase
        self.last_progress = time.monotonic()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def _monitor(self) -> None:
        poll_period = min(max(self.timeout_seconds / 8.0, 1.0), 10.0)
        while not self.stop_event.wait(poll_period):
            stalled_for = time.monotonic() - self.last_progress
            if stalled_for >= self.timeout_seconds:
                print(
                    f"[WATCHDOG] FATAL: no simulation progress for {stalled_for:.1f}s "
                    f"at step={self.step}, phase={self.phase}; dumping thread stacks.",
                    flush=True,
                )
                faulthandler.dump_traceback(all_threads=True)
                os._exit(3)


def run_pick(
    sim: sim_utils.SimulationContext,
    scene: InteractiveScene,
    watchdog: _SimulationStallWatchdog,
) -> bool:
    """Execute and validate the complete pick sequence."""
    robot = scene["robot"]
    near_cylinder = scene["near_cylinder"]
    far_cylinder = scene["far_cylinder"]
    (
        arm_joint_ids,
        ik_joint_ids,
        wrist_roll_id,
        jaw_joint_id,
        ee_body_id,
        collision_body_ids,
    ) = _resolve_robot_indices(robot)
    left_arm_joint_ids, left_arm_joint_names = robot.find_joints(
        LEFT_ARM_JOINT_NAMES, preserve_order=True
    )
    left_ee_body_ids, left_ee_body_names = robot.find_bodies(
        LEFT_ARM_EE_BODY_NAME, preserve_order=True
    )
    if len(left_arm_joint_ids) != len(LEFT_ARM_JOINT_NAMES) or len(left_ee_body_ids) != 1:
        raise RuntimeError(
            f"Could not resolve parked left arm. joints={left_arm_joint_names}, "
            f"ee={left_ee_body_names}"
        )
    left_collision_body_ids = {}
    for envelope_name in ARM_COLLISION_ENVELOPES:
        left_body_ids, left_body_names = robot.find_bodies(
            f"{envelope_name}_2", preserve_order=True
        )
        if len(left_body_ids) != 1:
            raise RuntimeError(
                f"Could not resolve left collision body {envelope_name}_2: {left_body_names}"
            )
        left_collision_body_ids[envelope_name] = left_body_ids[0]
    left_ee_body_id = left_ee_body_ids[0]
    head_joint_ids, head_joint_names = robot.find_joints(
        ["head_pan_joint", "head_tilt_joint"], preserve_order=True
    )
    if len(head_joint_ids) != 2:
        raise RuntimeError(f"Could not resolve calibrated head joints: {head_joint_names}")
    ee_jacobian_index = ee_body_id - 1 if robot.is_fixed_base else ee_body_id

    # Pose mode is essential here.  Position-only DLS lets the wrist attitude
    # drift during descent, which makes one sloped finger strike the cylinder
    # before it enters the gap even when the Cartesian center target is right.
    ik_cfg = DifferentialIKControllerCfg(command_type="pose", use_relative_mode=False, ik_method="dls")
    ik = DifferentialIKController(ik_cfg, num_envs=1, device=sim.device)
    sim_dt = sim.get_physics_dt()

    # Motion endpoints are assigned after target acquisition so RGB-D warm-up
    # cannot shorten any trajectory segment.
    initialization_end = INITIALIZATION_STEPS
    transit_end = 0
    approach_end = 0
    close_end = 0
    lift_end = 0
    validation_end = 0
    phase_segment_end = 0

    phase = "initialize"
    phase_start_step = 0
    phase_start_center = None
    center_goal = None
    target_object = None
    target_name = None
    target_initial_pos = None
    desired_orientation = None
    approach_axis = None
    grasp_center = None
    lift_center = None
    overhead_center = None
    hold_good_steps = 0
    success = False
    grasp_constraint = None
    grasp_attach_error = None
    rgbd_samples: dict[str, list[torch.Tensor]] = {"blue": [], "red": []}
    perception_centroids: dict[str, list[float]] = {}
    rgbd_required_frames = 5
    camera_position_b = None
    camera_rotation_b_ros = None
    min_camera_x = float("inf")
    min_camera_z = float("inf")
    minimum_geometry_clearance = float("inf")
    minimum_clearance_pair = None

    jaw_target = torch.tensor([[OPEN_JAW_POSITION]], device=sim.device)
    last_joint_target = robot.data.default_joint_pos[:, ik_joint_ids].clone()
    wrist_roll_target = torch.full((1, 1), WRIST_ROLL_GRASP_POSITION, device=sim.device)
    head_target = torch.tensor([[HEAD_PAN_POSITION, HEAD_TILT_POSITION]], device=sim.device)

    print(
        "[SCENE] table size="
        f"{TABLE_SIZE}, pose={TABLE_POS}, top_z={TABLE_POS[2] + TABLE_SIZE[2] / 2:.3f}"
    )
    print(
        "[SCENE] cylinder radius="
        f"{CYLINDER_RADIUS:.3f}, height={CYLINDER_HEIGHT:.3f}, mass={CYLINDER_MASS:.3f}"
    )
    print(f"[SCENE] candidates: near={NEAR_CYLINDER_POS}, far={FAR_CYLINDER_POS}")
    print(f"[SETUP] target_source={args_cli.target_source}")
    if args_cli.target_source == "rgbd":
        camera_position_b, camera_rotation_b_ros = _known_base_to_head_camera(sim.device)
        print(
            f"[PERCEPTION] camera=Head_RGBD_Camera, resolution={HEAD_CAMERA_WIDTH}x{HEAD_CAMERA_HEIGHT}, "
            f"head_pan={HEAD_PAN_POSITION:.3f}, head_tilt={HEAD_TILT_POSITION:.3f}"
        )
        print(
            f"[PERCEPTION] known T_base_camera position={camera_position_b.cpu().tolist()}, "
            f"R_base_camera_ros={camera_rotation_b_ros.cpu().tolist()}"
        )

    for step in range(args_cli.max_steps):
        root_pose_w = robot.data.root_pose_w
        ee_pose_w = robot.data.body_pose_w[:, ee_body_id]
        ee_pos_b, ee_quat_b = subtract_frame_transforms(
            root_pose_w[:, 0:3],
            root_pose_w[:, 3:7],
            ee_pose_w[:, 0:3],
            ee_pose_w[:, 3:7],
        )
        camera_pos_b = ee_pos_b + quat_apply(
            ee_quat_b, torch.tensor([GRIPPER_CAMERA_OFFSET_EE], device=sim.device)
        )
        if step < initialization_end and step % 50 == 0:
            print(
                f"[SETTLE_MONITOR] step={step}, "
                f"near={near_cylinder.data.root_pos_w[0].cpu().tolist()}, "
                f"far={far_cylinder.data.root_pos_w[0].cpu().tolist()}, "
                f"ee={ee_pos_b[0].cpu().tolist()}"
            )
        if step == initialization_end:
            left_clearances, _ = _geometry_clearances(
                robot,
                left_collision_body_ids,
                left_ee_body_id,
                sim.device,
                arm_label="Left",
            )
            left_min_pair, left_min_clearance = min(
                left_clearances.items(), key=lambda item: item[1]
            )
            print(
                f"[WRIST_SETUP] commanded_roll={WRIST_ROLL_GRASP_POSITION:.4f}, "
                f"actual_roll={float(robot.data.joint_pos[0, wrist_roll_id]):.4f}, "
                f"wrist_pitch={float(robot.data.joint_pos[0, ik_joint_ids[-1]]):.4f}, "
                f"ee_z={float(ee_pos_b[0, 2]):.4f}, wrist_camera_z={float(camera_pos_b[0, 2]):.4f}, "
                f"camera_above_ee={float(camera_pos_b[0, 2] - ee_pos_b[0, 2]):.4f}"
            )
            print(
                f"[PARKED_ARM_SETUP] joints={left_arm_joint_names}, "
                f"actual={robot.data.joint_pos[0, left_arm_joint_ids].cpu().tolist()}, "
                f"ee={robot.data.body_pos_w[0, left_ee_body_id].cpu().tolist()}, "
                f"closest={left_min_pair[0]}->{left_min_pair[1]}, "
                f"clearance={left_min_clearance:.4f}"
            )
        if step >= initialization_end:
            min_camera_x = min(min_camera_x, float(camera_pos_b[0, 0]))
            min_camera_z = min(min_camera_z, float(camera_pos_b[0, 2]))
        if step >= initialization_end and step % COLLISION_CHECK_INTERVAL == 0:
            clearances, component_aabbs = _geometry_clearances(
                robot,
                collision_body_ids,
                ee_body_id,
                sim.device,
            )
            current_pair, current_clearance = min(clearances.items(), key=lambda item: item[1])
            if current_clearance < minimum_geometry_clearance:
                minimum_geometry_clearance = current_clearance
                minimum_clearance_pair = current_pair
            if step % 100 == 0:
                print(
                    f"[COLLISION_CHECK] step={step}, phase={phase}, "
                    f"closest={current_pair[0]}->{current_pair[1]}, "
                    f"clearance={current_clearance:.4f}, "
                    f"path_min={minimum_geometry_clearance:.4f}, path_pair={minimum_clearance_pair}"
                )
            if current_clearance < MIN_GEOMETRY_CLEARANCE:
                component_min, component_max = component_aabbs[current_pair[0]]
                print(
                    f"[RESULT] FAILURE: step={step}, phase={phase}, "
                    f"geometry clearance {current_clearance:.4f} m below "
                    f"{MIN_GEOMETRY_CLEARANCE:.4f} m for {current_pair[0]}->{current_pair[1]}; "
                    f"component_aabb=({component_min.cpu().tolist()}, {component_max.cpu().tolist()})"
                )
                break

        should_acquire = (
            target_object is None
            and step >= initialization_end
            and (args_cli.target_source == "stage" or step % 5 == 0)
        )
        if should_acquire:
            if args_cli.target_source == "stage":
                stage = sim.stage
                near_stage_pos, near_stage_quat = _stage_world_pose(stage, "/World/envs/env_0/NearCylinder")
                far_stage_pos, far_stage_quat = _stage_world_pose(stage, "/World/envs/env_0/FarCylinder")
                robot_stage_pos, _ = _stage_world_pose(stage, "/World/envs/env_0/Robot")
                near_distance = math.dist(near_stage_pos[:2], robot_stage_pos[:2])
                far_distance = math.dist(far_stage_pos[:2], robot_stage_pos[:2])
                if near_distance <= far_distance:
                    target_object, target_name = near_cylinder, "NearCylinder"
                    target_stage_pos, target_stage_quat = near_stage_pos, near_stage_quat
                else:
                    target_object, target_name = far_cylinder, "FarCylinder"
                    target_stage_pos, target_stage_quat = far_stage_pos, far_stage_quat
                target_initial_pos = torch.tensor(target_stage_pos, device=sim.device)
                print(
                    f"[TARGET] stage NearCylinder pose={near_stage_pos}, quat={near_stage_quat}, "
                    f"d_xy={near_distance:.4f}"
                )
                print(
                    f"[TARGET] stage FarCylinder pose={far_stage_pos}, quat={far_stage_quat}, "
                    f"d_xy={far_distance:.4f}"
                )
                print(f"[TARGET] selected={target_name}, pose={target_stage_pos}, quat={target_stage_quat}")
            else:
                head_camera = scene["head_camera"]
                rgb = head_camera.data.output["rgb"][0]
                depth = head_camera.data.output["distance_to_image_plane"][0]
                if step == initialization_end:
                    print(
                        f"[PERCEPTION_CALIBRATION] head_joint_names={head_joint_names}, "
                        f"commanded={head_target[0].cpu().tolist()}, "
                        f"actual={robot.data.joint_pos[0, head_joint_ids].cpu().tolist()}, "
                        f"sensor_position_w={head_camera.data.pos_w[0].cpu().tolist()}, "
                        f"known_position_b={camera_position_b.cpu().tolist()}, "
                        f"intrinsics={head_camera.data.intrinsic_matrices[0].cpu().tolist()}"
                    )
                detections = estimate_colored_cylinders(
                    rgb=rgb,
                    depth=depth,
                    intrinsics=head_camera.data.intrinsic_matrices[0],
                    camera_position_b=camera_position_b,
                    camera_rotation_b_ros=camera_rotation_b_ros,
                    cylinder_height=CYLINDER_HEIGHT,
                )
                detected_labels = {detection.label for detection in detections}
                print(
                    f"[PERCEPTION] step={step}, rgb_shape={tuple(rgb.shape)}, depth_shape={tuple(depth.shape)}, "
                    f"detections={sorted(detected_labels)}"
                )
                for detection in detections:
                    rgbd_samples[detection.label].append(detection.centroid_b)
                    print(
                        f"[PERCEPTION] label={detection.label}, pixels={detection.point_count}, "
                        f"top_pixels={detection.top_point_count}, median_depth={detection.median_depth:.4f}, "
                        f"centroid_b={detection.centroid_b.cpu().tolist()}, "
                        f"d_xy={float(torch.linalg.norm(detection.centroid_b[:2])):.4f}, "
                        f"sample={len(rgbd_samples[detection.label])}/{rgbd_required_frames}"
                    )
                if args_cli.save_rgbd_debug and max(len(samples) for samples in rgbd_samples.values()) == 1:
                    _save_rgbd_debug_images(
                        rgb,
                        depth,
                        head_camera.data.intrinsic_matrices[0],
                        camera_position_b,
                        camera_rotation_b_ros,
                        args_cli.save_rgbd_debug,
                    )
                if all(len(samples) >= rgbd_required_frames for samples in rgbd_samples.values()):
                    averaged_detections = []
                    for label, samples in rgbd_samples.items():
                        stacked = torch.stack(samples[:rgbd_required_frames])
                        median_centroid = torch.median(stacked, dim=0).values
                        perception_centroids[label] = median_centroid.cpu().tolist()
                        averaged_detections.append(
                            CylinderDetection(
                                label=label,
                                centroid_b=median_centroid,
                                point_count=0,
                                median_depth=0.0,
                                top_point_count=0,
                            )
                        )
                        spread = torch.amax(torch.linalg.norm(stacked - median_centroid, dim=1))
                        print(
                            f"[PERCEPTION_FUSED] label={label}, frames={rgbd_required_frames}, "
                            f"centroid_b={median_centroid.cpu().tolist()}, max_spread={float(spread):.5f}"
                        )
                        if float(spread) > 0.015:
                            print(
                                f"[RESULT] FAILURE: unstable RGB-D centroid for {label}; "
                                f"max_spread={float(spread):.5f} m."
                            )
                            return False
                    selected_detection = select_nearest_detection(averaged_detections)
                    target_initial_pos = selected_detection.centroid_b.clone()
                    if selected_detection.label == "blue":
                        target_object, target_name = near_cylinder, "NearCylinder"
                    else:
                        target_object, target_name = far_cylinder, "FarCylinder"
                    print(
                        f"[TARGET] source=rgbd, selected={target_name}, color={selected_detection.label}, "
                        f"centroid_b={target_initial_pos.cpu().tolist()}, "
                        f"d_xy={float(torch.linalg.norm(target_initial_pos[:2])):.4f}"
                    )
                    if args_cli.validate_rgbd_ground_truth:
                        validation_error = torch.linalg.norm(target_object.data.root_pos_w[0] - target_initial_pos)
                        print(
                            f"[GT_VALIDATION_ONLY] selected rigid-body pose="
                            f"{target_object.data.root_pos_w[0].cpu().tolist()}, "
                            f"rgbd_position_error={float(validation_error):.4f}; not used for planning"
                        )
                elif step >= RGBD_ACQUISITION_DEADLINE:
                    print(
                        f"[RESULT] FAILURE: RGB-D acquisition timed out; "
                        f"blue_frames={len(rgbd_samples['blue'])}, red_frames={len(rgbd_samples['red'])}."
                    )
                    break

            if target_object is None:
                continue

            transit_end = step + TRANSIT_STEPS
            approach_end = transit_end + APPROACH_STEPS
            close_end = approach_end + CLOSE_STEPS
            lift_end = close_end + LIFT_STEPS
            validation_end = lift_end + LIFT_VALIDATION_STEPS
            desired_orientation = ee_quat_b.clone()
            # Initialize the rate limiter from the settled measured pose. This
            # prevents a stale/default target from causing a joint-space jump
            # at the first Cartesian command.
            last_joint_target = robot.data.joint_pos[:, ik_joint_ids].clone()
            local_offset = _grasp_center_offset(OPEN_JAW_POSITION, sim.device)
            local_forward = torch.tensor([[0.0, -1.0, 0.0]], device=sim.device)
            approach_axis = quat_apply(desired_orientation, local_forward)
            approach_axis[:, 2] = 0.0
            approach_axis /= torch.linalg.norm(approach_axis, dim=1, keepdim=True).clamp_min(1e-6)

            # With Wrist_Roll=+pi/2 the jaw opening is horizontal, the wrist
            # camera stays above the gripper, and the cylinder can pass between
            # the two fingers to their pad center.
            grasp_center = target_initial_pos.unsqueeze(0) + GRASP_DEPTH_OFFSET * approach_axis
            grasp_center[:, 2] += GRASP_HEIGHT_OFFSET
            lift_center = grasp_center + torch.tensor([[0.0, 0.0, LIFT_DISTANCE]], device=sim.device)
            phase = "transit"
            phase_start_step = step
            phase_start_center = ee_pos_b + quat_apply(ee_quat_b, local_offset)
            overhead_center = grasp_center.clone()
            overhead_center[:, 2] = max(SAFE_TRANSIT_HEIGHT, float(grasp_center[0, 2]) + 0.08)
            center_goal = overhead_center
            phase_segment_end = transit_end
            _print_phase("transit: move directly from upright home to above target", step, overhead_center)
            print(
                f"[PLAN] approach_axis={approach_axis[0].cpu().tolist()}, "
                f"public_phases=['transit', 'approach', 'close', 'lift'], "
                f"home_center={phase_start_center[0].cpu().tolist()}, "
                f"overhead_center={overhead_center[0].cpu().tolist()}, "
                f"grasp_center={grasp_center[0].cpu().tolist()}, "
                f"lift_center={lift_center[0].cpu().tolist()}"
            )

        if step == transit_end and target_object is not None:
            actual_center = ee_pos_b + quat_apply(
                ee_quat_b,
                _grasp_center_offset(float(robot.data.joint_pos[0, jaw_joint_id]), sim.device),
            )
            transit_error = float(torch.linalg.norm(actual_center - overhead_center))
            print(
                f"[WAYPOINT_CHECK] transit_error={transit_error:.4f}, "
                f"actual_center={actual_center[0].cpu().tolist()}, "
                f"target={overhead_center[0].cpu().tolist()}"
            )
            if transit_error > TRANSIT_GOAL_TOLERANCE:
                print(
                    f"[RESULT] FAILURE: transit did not reach the overhead target; "
                    f"error={transit_error:.4f} m exceeds {TRANSIT_GOAL_TOLERANCE:.4f} m."
                )
                break
            phase = "approach"
            phase_start_step = step
            phase_start_center = actual_center.clone()
            center_goal = grasp_center
            phase_segment_end = approach_end
            _print_phase("approach: descend vertically into grasp", step, grasp_center)

        if step == approach_end and target_object is not None:
            actual_center = ee_pos_b + quat_apply(
                ee_quat_b,
                _grasp_center_offset(float(robot.data.joint_pos[0, jaw_joint_id]), sim.device),
            )
            approach_error = float(torch.linalg.norm(actual_center - grasp_center))
            camera_path_clear = minimum_geometry_clearance >= MIN_GEOMETRY_CLEARANCE
            print(
                f"[WAYPOINT_CHECK] grasp actual_EE={ee_pos_b[0].cpu().tolist()}, "
                f"actual_center={actual_center[0].cpu().tolist()}, "
                f"center_error={approach_error:.4f}, "
                f"cylinder={target_object.data.root_pos_w[0].cpu().tolist()}, "
                f"camera={camera_pos_b[0].cpu().tolist()}, min_camera_x={min_camera_x:.4f}, "
                f"min_camera_z={min_camera_z:.4f}, geometry_path_clearance={minimum_geometry_clearance:.4f}, "
                f"closest_pair={minimum_clearance_pair}, "
                f"camera_path_clear={camera_path_clear}, "
                f"jaw={float(robot.data.joint_pos[0, jaw_joint_id]):.4f}, "
                f"joints={robot.data.joint_pos[0, arm_joint_ids].cpu().tolist()}"
            )
            if not camera_path_clear:
                print("[RESULT] FAILURE: gripper camera path violates the chassis clearance margin.")
                break
            if approach_error > APPROACH_GOAL_TOLERANCE:
                print(
                    f"[RESULT] FAILURE: approach did not reach the grasp target; "
                    f"error={approach_error:.4f} m exceeds {APPROACH_GOAL_TOLERANCE:.4f} m."
                )
                break
            phase = "close"
            phase_start_step = step
            phase_start_center = actual_center.clone()
            center_goal = grasp_center
            _print_phase("close gripper", step)

        if step == close_end and target_object is not None:
            cylinder_pos = target_object.data.root_pos_w[0]
            jaw_pos = float(robot.data.joint_pos[0, jaw_joint_id])
            grasp_center_est = ee_pos_b[0] + quat_apply(
                ee_quat_b,
                _grasp_center_offset(jaw_pos, sim.device),
            )[0]
            expected_contact_center = cylinder_pos.clone()
            expected_contact_center[2] += GRASP_HEIGHT_OFFSET
            center_error = float(torch.linalg.norm(expected_contact_center - grasp_center_est))
            xy_error = float(torch.linalg.norm(expected_contact_center[:2] - grasp_center_est[:2]))
            pad_contact_z = float(grasp_center_est[2]) + GRASP_PAD_CONTACT_Z_OFFSET
            sidewall_height = abs(float(cylinder_pos[2]) - pad_contact_z)
            sidewall_limit = CYLINDER_HEIGHT / 2.0 - GRASP_SIDEWALL_END_MARGIN
            at_contact_angle = abs(jaw_pos - CLOSED_JAW_POSITION) < 0.04
            centered = xy_error <= GRASP_MAX_XY_ERROR and sidewall_height <= sidewall_limit
            constrained = grasp_constraint is not None
            print(
                f"[GRASP_CHECK] jaw={jaw_pos:.4f} rad, center_error={center_error:.4f} m, "
                f"xy_error={xy_error:.4f}, sidewall_height={sidewall_height:.4f}, "
                f"sidewall_limit={sidewall_limit:.4f}, "
                f"at_contact_angle={at_contact_angle}, centered={centered}, constrained={constrained}, "
                f"attach_error={grasp_attach_error}, "
                f"actual_EE={ee_pos_b[0].cpu().tolist()}, cylinder={cylinder_pos.cpu().tolist()}, "
                f"grasp_center={grasp_center_est.cpu().tolist()}"
            )
            if not (at_contact_angle and centered and constrained):
                print("[RESULT] FAILURE: gripper did not establish a centered constrained grasp.")
                break
            phase = "lift"
            phase_start_step = step
            phase_start_center = grasp_center_est.unsqueeze(0).clone()
            center_goal = lift_center
            phase_segment_end = lift_end
            _print_phase("vertical lift (grasp-center target)", step, center_goal)

        if step == lift_end and target_object is not None:
            print(
                f"[LIFT_VALIDATE] step={step}: lift motion complete; "
                f"holding the same lift target for {LIFT_VALIDATION_STEPS} validation steps"
            )

        if target_object is not None and center_goal is not None:
            if phase in ("transit", "approach"):
                monitored_center = ee_pos_b + quat_apply(
                    ee_quat_b,
                    _grasp_center_offset(float(robot.data.joint_pos[0, jaw_joint_id]), sim.device),
                )
                object_displacement = float(
                    torch.linalg.norm(target_object.data.root_pos_w[0] - target_initial_pos)
                )
                if step % 100 == 0:
                    print(
                        f"[OBJECT_MONITOR] step={step}, phase={phase}, "
                        f"cylinder={target_object.data.root_pos_w[0].cpu().tolist()}, "
                        f"displacement={object_displacement:.4f}, "
                        f"grasp_center={monitored_center[0].cpu().tolist()}"
                    )
                if object_displacement > 0.05:
                    print(
                        f"[RESULT] FAILURE: cylinder was disturbed before close; "
                        f"displacement={object_displacement:.4f} m."
                    )
                    break
            if phase in ("transit", "approach", "lift"):
                alpha = _phase_alpha(step, phase_start_step, phase_segment_end - phase_start_step)
            else:
                alpha = 1.0
            commanded_center = phase_start_center + alpha * (center_goal - phase_start_center)
            desired_offset = quat_apply(
                desired_orientation,
                _grasp_center_offset(float(robot.data.joint_pos[0, jaw_joint_id]), sim.device),
            )
            commanded_ee = commanded_center - desired_offset
            # Keep the safe wrist/gripper attitude captured after initialization.
            # Feeding the current attitude back as the next target lets small
            # orientation errors accumulate and can swing a jaw down into the
            # table even while the Cartesian center is commanded upward.
            ik.set_command(torch.cat((commanded_ee, desired_orientation), dim=1))
            jacobian = robot.root_physx_view.get_jacobians()[:, ee_jacobian_index, :, ik_joint_ids]
            joint_pos = robot.data.joint_pos[:, ik_joint_ids]
            computed_target = ik.compute(ee_pos_b, ee_quat_b, jacobian, joint_pos)
            # Limit one-step target changes; this prevents the small arm from
            # striking the table due to a transient near-singular IK update.
            delta = torch.clamp(computed_target - last_joint_target, min=-0.025, max=0.025)
            last_joint_target = last_joint_target + delta
            robot.set_joint_position_target(last_joint_target, joint_ids=ik_joint_ids)

        if phase == "close":
            close_alpha = _phase_alpha(step, phase_start_step, close_end - phase_start_step)
            jaw_target[:] = OPEN_JAW_POSITION + close_alpha * (CLOSED_JAW_POSITION - OPEN_JAW_POSITION)
            if (
                grasp_constraint is None
                and float(robot.data.joint_pos[0, jaw_joint_id]) <= GRASP_ATTACH_JAW_POSITION
            ):
                cylinder_pos = target_object.data.root_pos_w[0]
                current_center = ee_pos_b[0] + quat_apply(
                    ee_quat_b,
                    _grasp_center_offset(float(robot.data.joint_pos[0, jaw_joint_id]), sim.device),
                )[0]
                expected_contact_center = cylinder_pos.clone()
                expected_contact_center[2] += GRASP_HEIGHT_OFFSET
                candidate_error = float(torch.linalg.norm(expected_contact_center - current_center))
                candidate_xy_error = float(
                    torch.linalg.norm(expected_contact_center[:2] - current_center[:2])
                )
                candidate_pad_contact_z = float(current_center[2]) + GRASP_PAD_CONTACT_Z_OFFSET
                candidate_sidewall_height = abs(float(cylinder_pos[2]) - candidate_pad_contact_z)
                sidewall_limit = CYLINDER_HEIGHT / 2.0 - GRASP_SIDEWALL_END_MARGIN
                if (
                    candidate_xy_error <= GRASP_MAX_XY_ERROR
                    and candidate_sidewall_height <= sidewall_limit
                ):
                    target_prim_path = f"/World/envs/env_0/{target_name}"
                    cylinder_quat = target_object.data.root_quat_w[0].unsqueeze(0)
                    relative_pos, relative_quat = subtract_frame_transforms(
                        robot.data.body_pos_w[:, ee_body_id],
                        robot.data.body_quat_w[:, ee_body_id],
                        cylinder_pos.unsqueeze(0),
                        cylinder_quat,
                    )
                    grasp_constraint = _create_preserving_fixed_joint(
                        sim.stage,
                        "/World/GraspConstraint",
                        "/World/envs/env_0/Robot/Fixed_Jaw",
                        target_prim_path,
                        relative_pos[0].cpu().tolist(),
                        relative_quat[0].cpu().tolist(),
                    )
                    grasp_attach_error = candidate_error
                    print(
                        f"[GRASP_ATTACH] jaw={float(robot.data.joint_pos[0, jaw_joint_id]):.4f}, "
                        f"center_error={candidate_error:.4f}, xy_error={candidate_xy_error:.4f}, "
                        f"sidewall_height={candidate_sidewall_height:.4f}, "
                        f"sidewall_limit={sidewall_limit:.4f}, body={target_prim_path}"
                    )
        if target_object is None:
            robot.set_joint_position_target(last_joint_target, joint_ids=ik_joint_ids)
        robot.set_joint_position_target(wrist_roll_target, joint_ids=[wrist_roll_id])
        robot.set_joint_position_target(jaw_target, joint_ids=[jaw_joint_id])
        robot.set_joint_position_target(head_target, joint_ids=head_joint_ids)
        scene.write_data_to_sim()
        sim.step()
        scene.update(sim_dt)
        watchdog.ping(step, phase)

        if target_object is not None and phase == "lift":
            cylinder_pos = target_object.data.root_pos_w[0]
            grasp_center_est = robot.data.body_pos_w[0, ee_body_id] + quat_apply(
                robot.data.body_quat_w[:, ee_body_id],
                _grasp_center_offset(float(robot.data.joint_pos[0, jaw_joint_id]), sim.device),
            )[0]
            height_gain = float(cylinder_pos[2] - target_initial_pos[2])
            follow_error = float(torch.linalg.norm(cylinder_pos - grasp_center_est))
            if step % 100 == 0:
                print(
                    f"[LIFT_CHECK] step={step}, cylinder_z={float(cylinder_pos[2]):.4f}, "
                    f"height_gain={height_gain:.4f}, follow_error={follow_error:.4f}"
                )
            if step >= lift_end and height_gain >= 0.08 and follow_error <= 0.06:
                hold_good_steps += 1
            elif step >= lift_end:
                hold_good_steps = 0

        if step >= validation_end and target_object is not None:
            cylinder_pos = target_object.data.root_pos_w[0]
            height_gain = float(cylinder_pos[2] - target_initial_pos[2])
            jaw_pos = float(robot.data.joint_pos[0, jaw_joint_id])
            success = hold_good_steps >= 100
            print(
                f"[RESULT] {'SUCCESS' if success else 'FAILURE'}: selected={target_name}, "
                f"initial_z={float(target_initial_pos[2]):.4f}, final_z={float(cylinder_pos[2]):.4f}, "
                f"height_gain={height_gain:.4f}, jaw={jaw_pos:.4f}, "
                f"stable_hold_steps={hold_good_steps}"
            )
            if args_cli.save_rgbd_debug and args_cli.target_source == "rgbd":
                summary = {
                    "success": success,
                    "selected": target_name,
                    "perception_centroids_b": perception_centroids,
                    "initial_z": float(target_initial_pos[2]),
                    "final_z": float(cylinder_pos[2]),
                    "height_gain": height_gain,
                    "jaw_position": jaw_pos,
                    "stable_hold_steps": hold_good_steps,
                    "minimum_geometry_clearance": minimum_geometry_clearance,
                    "minimum_clearance_pair": minimum_clearance_pair,
                }
                summary_path = Path(args_cli.save_rgbd_debug).resolve() / "run_summary.json"
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
                print(f"[RESULT] wrote reproducible run summary to {summary_path}")
            if not args_cli.keep_open:
                break

    else:
        print(f"[RESULT] FAILURE: timed out after {args_cli.max_steps} simulation steps.")

    if args_cli.keep_open:
        print("[INFO] --keep_open active; close Isaac Sim to exit.")
        while simulation_app.is_running():
            sim.step()
            watchdog.ping(args_cli.max_steps, "keep_open")
    return success


def main() -> int:
    if not XLEROBOT_USD_PATH.exists():
        raise FileNotFoundError(f"Could not find robot USD: {XLEROBOT_USD_PATH}")

    sim_cfg = sim_utils.SimulationCfg(
        dt=0.01,
        device=args_cli.device,
        physx=sim_utils.PhysxCfg(
            solver_type=1,
            min_position_iteration_count=8,
            max_position_iteration_count=32,
            min_velocity_iteration_count=2,
            max_velocity_iteration_count=8,
        ),
    )
    sim = sim_utils.SimulationContext(sim_cfg)
    sim.set_camera_view([1.35, -1.35, 1.20], [0.22, -0.02, 0.72])
    scene = InteractiveScene(PickSceneCfg(num_envs=1, env_spacing=2.0, replicate_physics=False))
    sim.reset()
    # Synchronize the configured upright home into PhysX before the first
    # physics step.  Setting actuator targets alone lets the robot briefly
    # spawn in the USD's horizontal pose and sweep through nearby objects while
    # settling, which is not a valid collision-free initial condition.
    robot = scene["robot"]
    initial_joint_pos = robot.data.default_joint_pos.clone()
    initial_joint_vel = robot.data.default_joint_vel.clone()
    robot.write_joint_state_to_sim(initial_joint_pos, initial_joint_vel)
    robot.set_joint_position_target(initial_joint_pos)
    robot.write_data_to_sim()
    robot.reset()
    sim.forward()
    print(f"[SETUP] loaded robot USD={XLEROBOT_USD_PATH}")
    watchdog = _SimulationStallWatchdog(args_cli.stall_timeout)
    watchdog.start()
    try:
        success = run_pick(sim, scene, watchdog)
    finally:
        watchdog.stop()
    return 0 if success else 2


if __name__ == "__main__":
    exit_code = main()
    # Full Kit teardown can stall in headless Isaac Sim 5.1 after a runtime
    # physics joint is authored.  Its supported immediate-exit path releases
    # the framework deterministically and preserves the process exit code.
    simulation_app.close(skip_cleanup=bool(args_cli.headless))
    sys.exit(exit_code)
