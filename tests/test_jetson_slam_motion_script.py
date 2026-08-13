from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "jetson_slam_motion_odom.sh"


def test_dry_run_is_read_only_and_live_is_blocked_pending_supervisor() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'config_path="configs/slam/base_to_gemini_candidate.yaml"' in text
    dry_run, live_block = text.split('if [[ "$dry_run" == true ]]; then', 1)[1].split(
        'echo "Motion VO live mode is blocked:', 1
    )
    assert '--mount "type=bind,src=$repo_root,dst=/workspace,readonly"' in dry_run
    assert "jetson_slam_exec.sh" not in dry_run
    assert "--gemini" not in dry_run
    assert "--interactive" not in dry_run
    assert "exit 2" in live_block
