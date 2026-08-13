import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
HOST_SCRIPT = ROOT / "scripts" / "jetson_slam_supervised_mapping.sh"
CONTAINER_SCRIPT = ROOT / "scripts" / "slam_supervised_mapping_container.sh"
ROBOT_EXEC_SCRIPT = ROOT / "scripts" / "jetson_robot_exec.sh"
SLAM_DOCKERFILE = ROOT / "deploy" / "slam" / "Dockerfile"


def test_supervised_mapping_has_one_locked_host_entrypoint() -> None:
    host = HOST_SCRIPT.read_text(encoding="utf-8")
    assert "jetson_slam_exec.sh" in host
    assert "--gemini --black --white --interactive" in host
    assert "slam_supervised_mapping_container.sh" in host


def test_robot_exec_stops_container_when_host_session_exits() -> None:
    script = ROBOT_EXEC_SCRIPT.read_text(encoding="utf-8")
    assert '--name "$container_name"' in script
    assert '--cidfile "$container_cidfile"' in script
    assert 'rm -f "$container_cidfile"' in script
    assert "trap cleanup_container EXIT" in script
    assert "trap 'exit 129' HUP" in script
    assert 'docker stop --timeout 10 "$container_ref"' in script
    assert "SIGKILL" in script
    assert "session_start" in script
    assert "setsid bash -c" in script
    assert "for attempt in {1..20}" in script


@pytest.mark.skipif(os.name == "nt", reason="requires Linux process and flock semantics")
@pytest.mark.parametrize("cid_delay_s", [0.0, 1.5])
def test_robot_exec_watchdog_cleans_fake_container_across_cid_race(
    tmp_path: Path, cid_delay_s: float
) -> None:
    required_commands = ("bash", "flock", "setsid")
    if any(shutil.which(command) is None for command in required_commands):
        pytest.skip("required Linux process tools are unavailable")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  run)
    shift
    cidfile=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    sleep "${FAKE_DOCKER_CID_DELAY:-0}"
    printf 'fake-container-id\\n' >"$cidfile"
    touch "$FAKE_DOCKER_STARTED"
    while [[ -e "$FAKE_DOCKER_STARTED" ]]; do sleep 0.1; done
    ;;
  inspect)
    [[ -e "$FAKE_DOCKER_STARTED" ]]
    ;;
  stop|kill)
    rm -f "$FAKE_DOCKER_STARTED"
    touch "$FAKE_DOCKER_STOPPED"
    ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    data_root = tmp_path / "data"
    calibration_root = tmp_path / "calibration"
    data_root.mkdir()
    calibration_root.mkdir()
    lock_path = tmp_path / "hardware.lock"
    started_path = tmp_path / "started"
    stopped_path = tmp_path / "stopped"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FORESTBRIDGE_DATA_ROOT": str(data_root),
            "FORESTBRIDGE_CALIBRATION_ROOT": str(calibration_root),
            "FORESTBRIDGE_HARDWARE_LOCK": str(lock_path),
            "FAKE_DOCKER_CID_DELAY": str(cid_delay_s),
            "FAKE_DOCKER_STARTED": str(started_path),
            "FAKE_DOCKER_STOPPED": str(stopped_path),
        }
    )
    process = subprocess.Popen(
        ["bash", str(ROBOT_EXEC_SCRIPT), "--", "sleep", "300"], env=env
    )
    try:
        if cid_delay_s == 0.0:
            deadline = time.monotonic() + 3.0
            while not started_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert started_path.exists()
        else:
            time.sleep(0.2)
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=3)

        deadline = time.monotonic() + 6.0
        while not stopped_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert stopped_path.exists()
        assert not started_path.exists()
        lock_status = 1
        while lock_status != 0 and time.monotonic() < deadline:
            lock_status = subprocess.run(
                ["flock", "--nonblock", str(lock_path), "true"], check=False
            ).returncode
            if lock_status != 0:
                time.sleep(0.05)
        assert lock_status == 0
    finally:
        if process.poll() is None:
            process.kill()


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
    assert "camera_width=640" in script
    assert "camera_height=480" in script
    assert "camera_fps=30" in script
    assert '--camera-width "$camera_width"' in script
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
    assert "enable_point_cloud:=false" in container
    assert 'camera-profile.txt' in container
    assert "must be all zero (device default) or all positive" in container
    assert 'capture_graph_contract_with_retry "-post"' in container
    assert "for attempt in 1 2 3" in container


def test_slam_image_contains_needed_base_transport_dependency() -> None:
    dockerfile = SLAM_DOCKERFILE.read_text(encoding="utf-8")
    assert "feetech-servo-sdk" in dockerfile
    assert "pyserial" in dockerfile
