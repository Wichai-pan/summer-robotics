import json
from pathlib import Path

import numpy as np
import pytest

from real_pick_blue_cylinder import (
    build_plan,
    cartesian_to_joints,
    execute_cartesian_trajectory,
    load_config,
    planar_ik,
    relative_ee_to_joints,
    target_frame_coordinates,
    transform_point,
)


HERE = Path(__file__).resolve().parent


def config_for_test():
    config = json.loads((HERE / "pick_config_v1.json").read_text(encoding="utf-8"))
    config["camera_to_shoulder_4x4"] = np.eye(4).tolist()
    config["target_offset_shoulder_m"] = [0.0, 0.0, 0.0]
    config["kinematics"]["tool_length_m"] = 0.05
    config["joint_limits_deg"] = {name: [-180.0, 180.0] for name in config["joint_limits_deg"]}
    config["joint_limits_deg"]["gripper"] = [0.0, 100.0]
    config["motion"]["approach_height_m"] = 0.02
    config["motion"]["lift_height_m"] = 0.03
    config["motion"]["grasp_offset_shoulder_m"] = [0.0, 0.0, 0.0]
    return config


def test_transform_point_translation():
    matrix = np.eye(4)
    matrix[:3, 3] = [1.0, 2.0, 3.0]
    assert np.allclose(transform_point(matrix, [0.1, 0.2, 0.3]), [1.1, 2.2, 3.3])


def test_build_plan_orders_vertical_waypoints():
    plan = build_plan(np.array([0.20, 0.0, 0.15]), 0.002, 15, config_for_test())
    assert plan.overhead_shoulder_m[2] > plan.grasp_shoulder_m[2]
    assert plan.lift_shoulder_m[2] > plan.grasp_shoulder_m[2]
    assert plan.samples == 15
    assert set(plan.grasp_joints_deg) == {
        "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"
    }


def test_target_offset_is_applied_before_planning():
    config = config_for_test()
    config["target_offset_shoulder_m"] = [0.01, -0.02, 0.005]
    plan = build_plan(np.array([0.20, 0.02, 0.15]), 0.002, 15, config)
    assert np.allclose(plan.target_shoulder_m, [0.21, 0.0, 0.155])


def test_target_frame_coordinates_reports_raw_and_adjusted_base_points():
    config = config_for_test()
    config["target_offset_shoulder_m"] = [0.01, -0.02, 0.005]
    raw, adjusted = target_frame_coordinates(np.array([0.20, 0.02, 0.15]), config)
    assert np.allclose(raw, [0.20, 0.02, 0.15])
    assert np.allclose(adjusted, [0.21, 0.0, 0.155])


def test_cartesian_phase_does_not_treat_tracking_lag_as_command_step():
    config = config_for_test()
    config["motion"]["control_hz"] = 100.0
    point = np.array([0.20, 0.0, 0.15])
    commanded = cartesian_to_joints(point, config) | {"gripper": 80.0}

    class LaggingRobot:
        def __init__(self):
            self.sent = []

        def get_observation(self):
            measured = dict(commanded)
            measured["shoulder_lift"] -= 3.44
            measured["wrist_roll"] -= 7.60
            return {f"{name}.pos": value for name, value in measured.items()}

        def send_action(self, action):
            self.sent.append(action)

    robot = LaggingRobot()
    execute_cartesian_trajectory(robot, point, point, 80.0, 0.02, config, "test")
    assert robot.sent


def test_workspace_field_is_not_required_or_enforced():
    config = config_for_test()
    config.pop("workspace_shoulder_m", None)
    plan = build_plan(np.array([0.20, 0.0, -0.02]), 0.002, 15, config)
    assert np.allclose(plan.target_shoulder_m, [0.20, 0.0, -0.02])


def test_new_joint_definition_for_straight_arm():
    shoulder, elbow, forearm = planar_ik(0.1159 + 0.1350 - 0.0001, 0.0, 0.1159, 0.1350)
    assert shoulder == pytest.approx(0.0, abs=4.0)
    assert elbow == pytest.approx(180.0, abs=4.0)
    assert forearm == pytest.approx(0.0, abs=4.0)


def test_downward_target_can_place_elbow_below_shoulder():
    config = load_config(HERE / "pick_config_v1.json")
    joints = relative_ee_to_joints(np.array([0.22, 0.0, -0.08]), config, -90.0)
    assert all(np.isfinite(value) for value in joints.values())


def test_same_height_horizontal_target_uses_upward_fold_with_lower_elbow():
    config = load_config(HERE / "pick_config_v1.json")
    config["joint_limits_deg"]["shoulder_lift"] = [-180.0, 110.0]
    joints = relative_ee_to_joints(np.array([0.35, 0.0, 0.0]), config, 0.0)
    assert joints["shoulder_pan"] == pytest.approx(0.0)
    assert joints["shoulder_lift"] == pytest.approx(-41.85, abs=0.2)
    assert joints["elbow_flex"] == pytest.approx(-13.21, abs=0.2)
    assert joints["wrist_flex"] == pytest.approx(-34.94, abs=0.2)


def test_raised_horizontal_target_uses_upward_fold():
    config = load_config(HERE / "pick_config_v1.json")
    joints = relative_ee_to_joints(np.array([0.35, 0.0, 0.12]), config, 0.0)
    assert joints["shoulder_pan"] == pytest.approx(0.0)
    assert joints["shoulder_lift"] == pytest.approx(6.24, abs=0.2)
    assert joints["elbow_flex"] == pytest.approx(-43.53, abs=0.2)
    assert joints["wrist_flex"] == pytest.approx(-52.71, abs=0.2)
    assert joints["wrist_roll"] == pytest.approx(180.0)
