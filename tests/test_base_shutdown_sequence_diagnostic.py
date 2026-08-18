import json
import subprocess
import sys
from pathlib import Path

from tools.base_shutdown_sequence_diagnostic import validate_preflight


def valid_preflight() -> dict[str, object]:
    return {
        "wheels": {
            str(motor_id): {
                "goal_velocity_raw": 0,
                "present_velocity_signed_raw": 0,
                "torque_enable": 0,
                "operating_mode": 1,
            }
            for motor_id in (7, 8, 9)
        }
    }


def test_preflight_accepts_zero_velocity_torque_off_wheels() -> None:
    assert validate_preflight(valid_preflight()) == []


def test_preflight_rejects_nonzero_goal_or_enabled_torque() -> None:
    record = valid_preflight()
    record["wheels"]["8"]["goal_velocity_raw"] = 1  # type: ignore[index]
    record["wheels"]["9"]["torque_enable"] = 1  # type: ignore[index]

    failures = validate_preflight(record)

    assert any("ID 8 goal_velocity_raw" in failure for failure in failures)
    assert any("ID 9 torque_enable" in failure for failure in failures)


def test_dry_run_does_not_import_hardware_modules(tmp_path: Path) -> None:
    (tmp_path / "scservo_sdk.py").write_text(
        "raise RuntimeError('hardware import attempted')\n", encoding="utf-8"
    )
    tool = Path(__file__).parents[1] / "tools" / "base_shutdown_sequence_diagnostic.py"
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
    assert payload["nonzero_velocity_commands"] == 0
