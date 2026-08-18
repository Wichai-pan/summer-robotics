import json
import subprocess
import sys
from pathlib import Path

from tools.base_bus_cadence_diagnostic import preflight_failures, read_cycle, summarize


class FakePacket:
    def __init__(self, communication: int = 0, torque: int = 0) -> None:
        self.communication = communication
        self.torque = torque

    def read2ByteTxRx(self, _port: object, _motor_id: int, _address: int) -> tuple[int, int, int]:
        return 0, self.communication, 0

    def read1ByteTxRx(self, _port: object, _motor_id: int, _address: int) -> tuple[int, int, int]:
        return self.torque, self.communication, 0


def test_summary_reports_collective_receive_timeouts() -> None:
    cycle = read_cycle(FakePacket(communication=-6), object(), 0)

    summary = summarize([cycle], 0)

    assert summary["reads"] == 9
    assert summary["failures"] == 9
    assert summary["communication_codes"] == {"-6": 9}


def test_summary_accepts_complete_successful_cycle() -> None:
    cycle = read_cycle(FakePacket(), object(), 0)

    summary = summarize([cycle], 0)

    assert summary["reads"] == 9
    assert summary["failures"] == 0
    assert summary["failure_rate"] == 0.0


def test_preflight_requires_all_three_wheel_torques_off() -> None:
    cycle = read_cycle(FakePacket(torque=1), object(), 0)

    failures = preflight_failures([cycle], 0)

    assert len(failures) == 3
    assert all("torque is not off" in failure for failure in failures)


def test_dry_run_does_not_import_hardware_modules(tmp_path: Path) -> None:
    blocker = tmp_path / "scservo_sdk.py"
    blocker.write_text("raise RuntimeError('hardware import attempted')\n", encoding="utf-8")
    tool = Path(__file__).parents[1] / "tools" / "base_bus_cadence_diagnostic.py"
    result = subprocess.run(
        [sys.executable, str(tool), "--dry-run"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hardware_access"] is False
    assert payload["register_writes"] == 0
    assert payload["wheel_ids"] == [7, 8, 9]
