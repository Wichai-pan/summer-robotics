from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "jetson_nav_then_act_pick_place.sh"
ACT_SCRIPT = Path(__file__).parents[1] / "scripts" / "jetson_act_trial.sh"


def test_pipeline_is_a_new_gated_orchestrator_over_existing_entrypoints() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'read -r -p "Type $pipeline_token to begin: "' in text
    assert 'pipeline_token="PIPELINE"' in text
    assert '"$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh"' in text
    assert '"$repo_root/scripts/jetson_act_trial.sh"' in text
    assert "--reference \"$mapping_reference\"" in text
    assert "--reference \"$grasp_reference\"" in text
    assert "return --execute" in text
    assert "RETURN WHITE ARM TO FOLDED TRAVEL POSE" in text
    assert "python3 tools/return_white_to_folded_pose.py --execute" in text
    assert "--skip-return" in text
    assert "--dock-entry-distance-m \"$dock_entry_distance_m\"" in text
    assert "--position-tolerance-m \"$position_tolerance_m\"" in text
    assert "set -euo pipefail" in text


def test_pipeline_defaults_to_current_table_docking_and_newer_act_model_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'database="/data/slam/mapping/20260830T095346Z/rtabmap.db"' in text
    assert 'goal_x="0.060"' in text
    assert 'goal_y="-0.372"' in text
    assert 'goal_yaw_deg="-90"' in text
    assert 'position_tolerance_m="0.050"' in text
    assert 'steps="600"' in text


def test_pipeline_auto_demo_requires_one_explicit_total_authorization() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "--auto-demo" in text
    assert 'pipeline_token="AUTO_PIPELINE"' in text
    assert "export FORESTBRIDGE_DEMO_ARMED=1" in text
    assert "No inner PLAN/MOVE/READY/ROLLOUT prompts" in text


def test_auto_demo_continues_to_final_folded_return() -> None:
    text = ACT_SCRIPT.read_text(encoding="utf-8")

    assert "continuing to the automatic folded return" in text
    assert "final folded return is withheld" not in text
