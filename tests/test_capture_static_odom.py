import subprocess
import sys
from pathlib import Path

from tools.capture_static_odom import StreamGate, has_valid_odom_pose


SCRIPT = Path(__file__).parents[1] / "tools" / "capture_static_odom.py"


def test_stream_gate_discards_warmup_then_records() -> None:
    gate = StreamGate()

    assert gate.observe("odom") is False
    assert gate.observe("odom_info") is False

    gate.start_recording()

    assert gate.observe("odom") is True
    assert gate.observe("odom_info") is True


def test_odom_pose_validation_rejects_uninitialized_quaternion() -> None:
    assert has_valid_odom_pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    assert not has_valid_odom_pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0))
    assert not has_valid_odom_pose((float("nan"), 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def test_stream_gate_rejects_incomplete_warmup() -> None:
    gate = StreamGate()
    gate.observe("odom")

    try:
        gate.start_recording()
    except RuntimeError as error:
        assert "odom_info" in str(error)
    else:
        raise AssertionError("incomplete warmup was accepted")


def test_stream_gate_reports_missing_streams_before_recording() -> None:
    gate = StreamGate()
    assert gate.missing_streams() == {"odom", "odom_info"}

    gate.observe("odom")
    assert gate.missing_streams() == {"odom_info"}

    gate.observe("odom_info")
    assert gate.missing_streams() == set()


def test_dry_run_does_not_require_ros() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--warmup", "2"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ROS not imported" in result.stdout


def test_non_positive_warmup_is_rejected() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--warmup", "0"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--warmup must be positive" in result.stderr


def test_non_positive_warmup_timeout_is_rejected() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--warmup-timeout", "0"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--warmup-timeout must be positive" in result.stderr
