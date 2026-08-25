from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "jetson_nav_then_act_pick_place.sh"


def test_pipeline_is_a_new_gated_orchestrator_over_existing_entrypoints() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'read -r -p "Type PIPELINE to begin the mapping-gimbal return: "' in text
    assert '"$repo_root/scripts/jetson_slam_nav2_supervised_execute.sh"' in text
    assert '"$repo_root/scripts/jetson_act_trial.sh"' in text
    assert "--reference \"$mapping_reference\"" in text
    assert "--reference \"$grasp_reference\"" in text
    assert "return --execute" in text
    assert "--dock-entry-distance-m \"$dock_entry_distance_m\"" in text
    assert "--position-tolerance-m \"$position_tolerance_m\"" in text
    assert "set -euo pipefail" in text


def test_pipeline_defaults_to_current_table_docking_and_newer_act_model_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'database="/data/slam/mapping/20260825T131710Z/rtabmap.db"' in text
    assert 'goal_x="0.052"' in text
    assert 'goal_y="-0.357"' in text
    assert 'goal_yaw_deg="-90"' in text
    assert 'position_tolerance_m="0.025"' in text
    assert 'steps="600"' in text
