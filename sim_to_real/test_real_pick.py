import json
from pathlib import Path

import numpy as np
import pytest

from real_pick_blue_cylinder import (
    SafetyError,
    build_plan,
    cartesian_to_joints,
    load_config,
    transform_point,
)


HERE = Path(__file__).resolve().parent


def config_for_test():
    config = json.loads((HERE / "pick_config.example.json").read_text(encoding="utf-8"))
    config["camera_to_base_4x4"] = np.eye(4).tolist()
    config["right_shoulder_position_base_m"] = [0.0, 0.0, 0.0]
    config["workspace_base_m"] = {"x": [0.0, 0.5], "y": [-0.2, 0.2], "z": [0.0, 0.5]}
    config["kinematics"]["tool_length_m"] = 0.05
    config["joint_limits_deg"] = {name: [-180.0, 180.0] for name in config["joint_limits_deg"]}
    config["joint_limits_deg"]["gripper"] = [0.0, 100.0]
    config["motion"]["approach_height_m"] = 0.02
    config["motion"]["lift_height_m"] = 0.03
    config["motion"]["grasp_offset_base_m"] = [0.0, 0.0, 0.0]
    return config


def test_transform_point_translation():
    matrix = np.eye(4)
    matrix[:3, 3] = [1.0, 2.0, 3.0]
    assert np.allclose(transform_point(matrix, [0.1, 0.2, 0.3]), [1.1, 2.2, 3.3])


def test_build_plan_orders_vertical_waypoints():
    plan = build_plan(np.array([0.20, 0.0, 0.08]), 0.002, 15, config_for_test())
    assert plan.overhead_base_m[2] > plan.grasp_base_m[2]
    assert plan.lift_base_m[2] > plan.grasp_base_m[2]
    assert plan.samples == 15
    assert set(plan.grasp_joints_deg) == {
        "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"
    }


def test_workspace_violation_is_rejected():
    with pytest.raises(SafetyError, match="outside workspace"):
        build_plan(np.array([0.80, 0.0, 0.08]), 0.002, 15, config_for_test())


def test_example_configuration_is_deliberately_locked():
    config = load_config(HERE / "pick_config.example.json")
    assert config["calibrated"] is False
    assert "safe_home_joints_deg" not in config


def test_urdf_approximation_can_plan_simulation_cylinder_position():
    config = load_config(HERE / "pick_config.example.json")
    joints = cartesian_to_joints(np.array([0.28, -0.04, 0.84]), config)
    assert all(np.isfinite(value) for value in joints.values())
