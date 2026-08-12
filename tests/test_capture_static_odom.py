import subprocess
import sys
from pathlib import Path

from tools.capture_static_odom import StreamGate


SCRIPT = Path(__file__).parents[1] / "tools" / "capture_static_odom.py"


def test_stream_gate_discards_warmup_then_records() -> None:
    gate = StreamGate()

    assert gate.observe("odom") is False
    assert gate.observe("odom_info") is False

    gate.start_recording()

    assert gate.observe("odom") is True
    assert gate.observe("odom_info") is True


def test_stream_gate_rejects_incomplete_warmup() -> None:
    gate = StreamGate()
    gate.observe("odom")

    try:
        gate.start_recording()
    except RuntimeError as error:
        assert "odom_info" in str(error)
    else:
        raise AssertionError("incomplete warmup was accepted")


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
