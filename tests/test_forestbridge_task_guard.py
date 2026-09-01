from pathlib import Path

from forestbridge_camera_monitor import foreground_task_active


def test_missing_task_guard_is_inactive(tmp_path: Path) -> None:
    assert foreground_task_active(tmp_path / "missing") is False


def test_stale_task_guard_is_removed(tmp_path: Path) -> None:
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "owner").write_text("999999999\n1\n", encoding="utf-8")
    old = guard.stat().st_mtime - 60
    import os

    os.utime(guard, (old, old))
    assert foreground_task_active(guard) is False
    assert not guard.exists()
