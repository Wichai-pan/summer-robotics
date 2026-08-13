from pathlib import Path


ROOT = Path(__file__).parents[1]
HOST_SCRIPT = ROOT / "scripts" / "jetson_slam_supervised_mapping.sh"
CONTAINER_SCRIPT = ROOT / "scripts" / "slam_supervised_mapping_container.sh"
SLAM_DOCKERFILE = ROOT / "deploy" / "slam" / "Dockerfile"


def test_supervised_mapping_has_one_locked_host_entrypoint() -> None:
    host = HOST_SCRIPT.read_text(encoding="utf-8")
    assert "jetson_slam_exec.sh" in host
    assert "--gemini --black --white --interactive" in host
    assert "slam_supervised_mapping_container.sh" in host


def test_container_session_checks_pose_before_base_torque_and_saves_mapping() -> None:
    script = CONTAINER_SCRIPT.read_text(encoding="utf-8")
    assert "gemini_gimbal_pose.py" in script
    assert "check --tolerance-deg 1.0" in script
    assert "slam_base_camera_transform.py validate" in script
    assert "Type MAP to start" in script
    assert "Do not press W/S yet" in script
    assert "--mode mapping" in script
    assert "--ready-file" in script
    assert "base_keyboard.py --terminal" in script
    assert "base_runtime=$((duration - 3))" in script
    assert script.index("gemini_gimbal_pose.py") < script.index("base_keyboard.py --terminal")


def test_mapping_finalizes_database_and_has_no_hardware_software_smoke() -> None:
    container = (ROOT / "scripts" / "slam_static_odom_container.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "jetson_slam_mapping_software_smoke.sh").read_text(encoding="utf-8")
    assert 'stop_process_group "$mapping_pid"' in container
    assert "--mode mapping" in smoke
    assert "--mount" in smoke
    assert "/dev/" not in smoke
    assert 'RGBD/CreateOccupancyGrid:="true"' in container
    assert 'Grid/FromDepth:="true"' in container


def test_slam_image_contains_needed_base_transport_dependency() -> None:
    dockerfile = SLAM_DOCKERFILE.read_text(encoding="utf-8")
    assert "feetech-servo-sdk" in dockerfile
    assert "pyserial" in dockerfile
