import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.base_wheel_feedback import (
    STS3215RawFeedbackSource,
    STS3215WheelFeedbackSource,
    load_sts_config,
    prepare_verified_wheels_stopped,
    shutdown_wheels,
)
from tools.slam_fused_graph_contract import EXPECTED_TF, validate_contract
from tools.slam_imu_contract import validate as validate_imu


ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_CONFIG = ROOT / "configs/slam/sts3215_wheel_feedback_unresolved.json"
GRAPH_CONFIG = ROOT / "configs/slam/fused_slam_graph.json"
IMU_CONFIG = ROOT / "configs/slam/gemini_imu_unresolved.json"
EKF_CONFIG = ROOT / "configs/slam/ekf_fused_odom.yaml"


def test_unresolved_feedback_cannot_be_used_live() -> None:
    parsed = load_sts_config(FEEDBACK_CONFIG, require_resolved=False)
    assert parsed["velocity_unit_rad_s_per_raw"] is None
    with pytest.raises(ValueError, match="unresolved"):
        load_sts_config(FEEDBACK_CONFIG, require_resolved=True)
    source = STS3215RawFeedbackSource("never-opened")
    assert source.port == "never-opened"
    assert "scservo_sdk" not in sys.modules


def test_feedback_config_rejects_bad_unit_and_wrong_ids(tmp_path: Path) -> None:
    data = json.loads(FEEDBACK_CONFIG.read_text(encoding="utf-8"))
    for mutation in (
        {"velocity_unit_rad_s_per_raw": float("nan")},
        {"motor_ids": [1, 7, 8, 9]},
    ):
        bad = {**data, **mutation}
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            load_sts_config(path, require_resolved=False)


def test_live_feedback_requires_wrap_sign_limits_and_bounded_serial_timeout(
    tmp_path: Path,
) -> None:
    data = json.loads(FEEDBACK_CONFIG.read_text(encoding="utf-8"))
    data.update(
        status="verified",
        velocity_unit_rad_s_per_raw=0.01,
        expected_velocity_unit_factor_raw=1,
        expected_feedback_hz=30.0,
        pose_covariance_diagonal=[1.0] * 6,
        twist_covariance_diagonal=[1.0] * 6,
        position_cross_turn_behavior="wraps-4096",
        feedback_sign_by_id={"7": 1, "8": 1, "9": 1},
        max_gap_s=0.2,
        max_age_s=0.1,
        max_wheel_speed_rad_s=80.0,
        max_wheel_accel_rad_s2=300.0,
    )
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="unresolved"):
        load_sts_config(path, require_resolved=True)
    data["serial_read_timeout_s"] = 0.01
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_sts_config(path, require_resolved=True)["status"] == "verified"


def test_sign_magnitude_feedback_decoding() -> None:
    assert STS3215WheelFeedbackSource._decode_sign_magnitude(123) == 123
    assert STS3215WheelFeedbackSource._decode_sign_magnitude(0x8000 | 123) == -123


def test_wheel_shutdown_attempts_zero_and_torque_off_for_every_id() -> None:
    calls: list[tuple[str, int]] = []

    class Packet:
        def write2ByteTxOnly(self, _port: object, motor_id: int, _address: int, _value: int):
            calls.append(("zero", motor_id))
            if motor_id == 7:
                raise RuntimeError("broken zero")
            return 0

        def write1ByteTxOnly(self, _port: object, motor_id: int, _address: int, _value: int):
            calls.append(("torque-off", motor_id))
            return 1 if motor_id == 8 else 0

    errors = shutdown_wheels(Packet(), object(), 0)
    assert [call for call in calls if call[0] == "zero"] == [
        ("zero", motor_id) for motor_id in (7, 8, 9)
    ]
    assert [call for call in calls if call[0] == "torque-off"] == [
        ("torque-off", motor_id) for motor_id in (7, 8, 9)
    ]
    assert len(errors) == 2


def test_fused_preflight_refuses_mode_change_and_zeros_before_torque() -> None:
    events: list[tuple[str, int]] = []

    class Packet:
        def __init__(self, bad_id: int | None = None):
            self.bad_id = bad_id

        def read1ByteTxRx(self, _port: object, motor_id: int, _address: int):
            return (0 if motor_id == self.bad_id else 1), 0, 0

        def write1ByteTxRx(self, _port: object, motor_id: int, _address: int, _value: int):
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

    prepare_verified_wheels_stopped(Packet(), object(), 0, GroupWriter)
    assert events == [("zero", 0), ("torque", 7), ("torque", 8), ("torque", 9)]

    events.clear()
    with pytest.raises(RuntimeError, match="refusing to change mode"):
        prepare_verified_wheels_stopped(Packet(bad_id=8), object(), 0, GroupWriter)
    assert events == []


def test_tf_publishers_are_exclusive_and_conflicts_fail() -> None:
    data = json.loads(GRAPH_CONFIG.read_text(encoding="utf-8"))
    validate_contract(data)
    assert data["tf_owners"] == EXPECTED_TF
    assert data["hardware_ownership"]["white_board"] == {
        "owner": "base_wheel_odometry",
        "motor_ids": [7, 8, 9],
        "readers": ["base_wheel_odometry"],
        "writers": ["base_wheel_odometry"],
    }
    bad = json.loads(json.dumps(data))
    bad["tf_owners"]["odom->base_link"] = "rtabmap"
    with pytest.raises(ValueError):
        validate_contract(bad)

    bad = json.loads(json.dumps(data))
    bad["hardware_ownership"]["white_board"]["readers"].append("base_keyboard")
    with pytest.raises(ValueError, match="one owner"):
        validate_contract(bad)


def test_route_has_no_lidar_rgbd_odometry_or_slam_toolbox() -> None:
    data = json.loads(GRAPH_CONFIG.read_text(encoding="utf-8"))
    assert "/scan" in data["forbidden_topics"]
    assert "rgbd_odometry" in data["forbidden_nodes"]
    assert "slam_toolbox" in data["forbidden_nodes"]
    script = (ROOT / "scripts/slam_fused_mapping_container.sh").read_text(encoding="utf-8")
    assert "rtabmap_slam rtabmap" in script
    assert "rgbd_odometry" not in script
    assert "/scan" not in script
    assert "-r odometry/filtered:=/odom" in script
    assert "-r odom:=/odom" in script
    assert "'odom_frame_id:='" in script
    assert "database_path" in script
    assert "localization database does not exist" in script
    assert "--enable-control --confirmed" in script
    assert "base_keyboard_ros.py --live" in script
    assert "--xy-speed-mps 0.04" in script
    assert "--theta-speed-deg-s 12" in script
    assert "--max-runtime-s 120" in script
    assert "ros2 topic echo --once /camera/gyro_accel/sample" in script
    assert "Gemini IMU topic did not appear" in script


def test_dry_runs_do_not_import_ros_or_hardware() -> None:
    commands = [
        ("tools/base_wheel_feedback.py", ["--dry-run"]),
        ("tools/base_odometry_ros.py", ["--dry-run"]),
        ("tools/base_keyboard_ros.py", ["--dry-run"]),
    ]
    for script, arguments in commands:
        snippet = (
            "import runpy,sys; sys.path.insert(0,'tools'); "
            f"sys.argv=['{script}',*{arguments!r}]; "
            f"script={script!r}; "
            "\ntry: runpy.run_path(script,run_name='__main__')"
            "\nexcept SystemExit as exc: assert exc.code in (None,0)"
            "\nassert 'scservo_sdk' not in sys.modules"
            "\nassert 'rclpy' not in sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-c", snippet], cwd=ROOT, text=True, capture_output=True
        )
        assert completed.returncode == 0, completed.stderr


def test_host_dry_run_does_not_invoke_docker_or_lock() -> None:
    script = (ROOT / "scripts/jetson_fused_slam.sh").read_text(encoding="utf-8")
    dry_block = script.split('if [[ "$dry_run" == true ]]', 1)[1].split("fi", 1)[0]
    assert "docker" not in dry_block.lower()
    assert "jetson_slam_exec" not in dry_block
    assert "flock" not in dry_block


def test_dockerfile_declares_fusion_without_nav2() -> None:
    dockerfile = (ROOT / "deploy/slam/Dockerfile").read_text(encoding="utf-8")
    assert "ros-humble-robot-localization" in dockerfile
    assert "nav2" not in dockerfile.lower()


def test_imu_fields_stay_disabled_until_axis_is_measured() -> None:
    config = (ROOT / "configs/slam/ekf_fused_odom.yaml").read_text(encoding="utf-8")
    imu_vector = config.split("imu0_config:", 1)[1].split("imu0_queue_size:", 1)[0]
    assert "true" not in imu_vector
    assert "axis/sign are not yet verified" in config
    assert validate_imu(IMU_CONFIG, EKF_CONFIG, require_live=False)["status"] == "unresolved"
    with pytest.raises(ValueError, match="unresolved"):
        validate_imu(IMU_CONFIG, EKF_CONFIG, require_live=True)


def test_negative_post_tf_imu_yaw_sign_cannot_unlock_live(tmp_path: Path) -> None:
    data = json.loads(IMU_CONFIG.read_text(encoding="utf-8"))
    data.update(
        status="verified",
        yaw_rate_axis="y",
        yaw_rate_sign_in_base=-1,
        angular_velocity_covariance_verified=True,
    )
    path = tmp_path / "imu.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="positive post-TF sign"):
        validate_imu(path, EKF_CONFIG, require_live=True)


def test_ros_live_path_contains_real_publisher() -> None:
    source = (ROOT / "tools/base_odometry_ros.py").read_text(encoding="utf-8")
    assert 'create_publisher(Odometry, "/wheel/odom"' in source
    assert "publisher.publish(message)" in source
    assert "STS3215WheelFeedbackSource" in source
    assert 'create_subscription(Twist, "/cmd_vel"' in source
    assert "sample.monotonic_s - monotonic_anchor_s" in source
    feedback = (ROOT / "tools/base_wheel_feedback.py").read_text(encoding="utf-8")
    assert "write_wheel_velocities(command_writer" in feedback
    assert "prepare_verified_wheels_stopped" in feedback
    assert "GroupSyncWrite" in feedback
    assert "stop_requested=stop_event.is_set" in source
    assert "setPacketTimeoutMillis(timeout_ms)" in feedback
    assert 'resolve_port(BOARDS["white"], override=args.port)' in source
    assert 'resolve_port(BOARDS["white"], override=args.port)' in feedback
    assert "refusing to change mode" in feedback
