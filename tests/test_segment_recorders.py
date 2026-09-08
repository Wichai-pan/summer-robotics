import ast
from pathlib import Path

from manipulation_state_machine import State, StateMachine, pick_frames_enabled, place_frames_enabled

ROOT = Path(__file__).resolve().parents[1]


def parsed(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"))


def string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_pick_hold_has_distinct_hold_and_release_confirmations() -> None:
    literals = string_literals(parsed("tools/black_leads_white_pick_hold.py"))
    assert "h" in literals
    assert "r" in literals
    assert "RELEASE" in literals
    assert "operator_cancelled_before_hold" in literals
    assert "recording_timeout_without_hold" in literals
    assert "operator_global_abort_during_hold" in literals


def test_new_segment_recorders_both_have_global_abort_key() -> None:
    for path in (
        "tools/black_leads_white_pick_hold.py",
        "tools/black_leads_white_place_release.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert 'GLOBAL_ABORT_KEY = "x"' in source
        assert "State.ABORTED" in source


def test_combined_session_uses_two_independent_recorders_and_a_clean_gap() -> None:
    source = (ROOT / "tools/black_leads_white_pick_hold_place.py").read_text(
        encoding="utf-8"
    )
    assert '"--pick-record-root"' in source
    assert '"--place-record-root"' in source
    assert "pick_recorder.stop_capture()" in source
    assert 'if key == "b"' in source
    assert "place_recorder = make_recorder(args, pick=False)" in source
    assert source.index("pick_recorder.stop_capture()") < source.index('if key == "b"')
    assert source.index('if key == "b"') < source.index(
        "place_recorder = make_recorder(args, pick=False)"
    )


def test_combined_session_does_not_use_grasp_or_release_telemetry_as_labels() -> None:
    source = (ROOT / "tools/black_leads_white_pick_hold_place.py").read_text(
        encoding="utf-8"
    )
    assert "Present_Load" not in source
    assert "Present_Current" not in source
    assert "release_min_position" not in source
    assert "latch_gripper_from_feedback" in source


def test_combined_wrist_hold_reseeds_position_after_mode_switch() -> None:
    tree = parsed("tools/black_leads_white_pick_hold_place.py")
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "wrist_to_position_hold"
    )
    source = ast.unparse(function)
    mode_write = source.index("write('Operating_Mode'")
    position_read = source.index("position_mode_raw = wait_for_mode_wrist_raw")
    goal_write = source.index("'Goal_Position', WRIST, position_mode_raw")
    assert mode_write < position_read < goal_write
    assert "'Goal_Position', WRIST, velocity_mode_raw" not in source


def test_combined_wrist_velocity_rebases_after_mode_switch() -> None:
    tree = parsed("tools/black_leads_white_pick_hold_place.py")
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "wrist_to_velocity_follow"
    )
    source = ast.unparse(function)
    mode_write = source.index("write('Operating_Mode'")
    zero_velocity = source.index("write('Goal_Velocity'")
    velocity_read = source.index("velocity_mode_raw = wait_for_mode_wrist_raw")
    enable = source.index("enable_torque(WRIST)")
    assert mode_write < zero_velocity < velocity_read < enable


def test_pick_defers_success_save_until_hold_is_safely_ended() -> None:
    source = (ROOT / "tools/black_leads_white_pick_hold.py").read_text(encoding="utf-8")
    assert "recorder.stop_capture()" in source
    assert "hold_ended_without_success_confirmation" in source
    assert "finalize_thread" not in source


def test_recorder_can_stop_cameras_without_deciding_episode() -> None:
    tree = parsed("tools/act_episode_recorder.py")
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "stop_capture" in methods


def test_place_release_uses_distinct_start_and_end_pose_arguments() -> None:
    literals = string_literals(parsed("tools/black_leads_white_place_release.py"))
    assert "--carry-pose-json" in literals
    assert "--empty-folded-pose-json" in literals
    assert "place-release collection requires --record-root" in literals


def test_original_recorder_was_not_given_segment_specific_arguments() -> None:
    literals = string_literals(parsed("tools/black_leads_white_wrap_safe.py"))
    assert "--carry-pose-json" not in literals
    assert "--empty-folded-pose-json" not in literals


def test_pick_state_rejects_skipping_operator_v_boundary() -> None:
    machine = StateMachine(State.PREPARE_PICK)
    machine.transition(State.RECORD_PICK)
    try:
        machine.transition(State.FINALIZE_PICK)
    except RuntimeError as exc:
        assert "illegal state transition" in str(exc)
    else:
        raise AssertionError("operator v boundary was bypassed")


def test_v_directly_accepts_grasp_without_a_telemetry_state() -> None:
    machine = StateMachine(State.RECORD_PICK)
    machine.transition(State.RETRACT_TO_HOLD)
    machine.transition(State.FINALIZE_PICK)
    assert machine.state is State.FINALIZE_PICK


def test_pick_script_has_no_grasp_or_fixed_carry_classifier() -> None:
    source = (ROOT / "tools/black_leads_white_pick_hold.py").read_text(encoding="utf-8")
    assert "verify_grasp" not in source
    assert "VERIFY_GRASP" not in source
    assert "VERIFY_CARRY" not in source
    assert "carry_pose_reference_for_episode" not in source
    assert "end_violations" not in source
    assert "gripper_latched_command" in source


def test_global_abort_is_legal_from_every_live_state() -> None:
    for state in State:
        if state in {State.DONE, State.ABORTED}:
            continue
        machine = StateMachine(state)
        machine.transition(State.ABORTED)
        assert machine.state is State.ABORTED


def test_complete_pick_and_place_state_paths_are_legal() -> None:
    pick = StateMachine(State.PREPARE_PICK)
    for state in (
        State.RECORD_PICK,
        State.RETRACT_TO_HOLD,
        State.FINALIZE_PICK,
        State.HOLD,
        State.WAIT_FOR_PLACE,
        State.PREPARE_PLACE,
        State.RECORD_PLACE,
        State.VERIFY_PLACE,
        State.VERIFY_RELEASE,
        State.RETURN_EMPTY,
        State.VERIFY_EMPTY,
        State.FINALIZE_PLACE,
        State.DONE,
    ):
        pick.transition(state)
    assert pick.state is State.DONE


def test_recording_boundaries_exclude_hold_navigation_and_finalization() -> None:
    assert pick_frames_enabled(State.RECORD_PICK)
    assert pick_frames_enabled(State.RETRACT_TO_HOLD)
    assert not pick_frames_enabled(State.HOLD)
    assert not pick_frames_enabled(State.WAIT_FOR_PLACE)
    assert place_frames_enabled(State.RECORD_PLACE)
    assert place_frames_enabled(State.VERIFY_RELEASE)
    assert place_frames_enabled(State.RETURN_EMPTY)
    assert not place_frames_enabled(State.FINALIZE_PLACE)
