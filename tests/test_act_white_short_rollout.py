import pytest

from act_white_short_rollout import (
    GripperContactSupervisor,
    action_dict,
    clamp_position_to_total_envelope,
    clamp_rollout_live_state,
    intersect_position_action_with_state_bounds,
    keep_wrist_velocity_inside_state_support,
    rollout_guarded_action,
    summarize_policy_chunks,
    total_travel_violations,
)


def test_gripper_supervisor_latches_contact_holds_then_releases() -> None:
    supervisor = GripperContactSupervisor(
        minimum_position=7.0,
        minimum_load_percent=15.0,
        minimum_current_raw=15,
        confirmation_s=0.3,
        hold_offset=1.25,
        release_position=20.0,
        release_confirmation_s=0.2,
        maximum_hold_s=15.0,
    )
    first = supervisor.update(
        now_s=0.0,
        present_position=9.4,
        requested_position=8.0,
        policy_requested_position=5.0,
        load_raw=270,
        current_raw=34,
    )
    assert first["latched"] is False
    latched = supervisor.update(
        now_s=0.31,
        present_position=9.2,
        requested_position=7.0,
        policy_requested_position=5.0,
        load_raw=268,
        current_raw=33,
    )
    assert latched["event"] == "contact_latched"
    assert latched["guarded_position"] == pytest.approx(7.95)
    held = supervisor.update(
        now_s=1.0,
        present_position=9.0,
        requested_position=5.0,
        policy_requested_position=5.0,
        load_raw=260,
        current_raw=30,
    )
    assert held["guard_reason"] == "grasp_contact_hold"
    assert held["guarded_position"] == pytest.approx(7.95)
    release_candidate = supervisor.update(
        now_s=2.0,
        present_position=9.0,
        requested_position=10.0,
        policy_requested_position=40.0,
        load_raw=250,
        current_raw=28,
    )
    assert release_candidate["event"] is None
    assert release_candidate["latched"] is True
    released = supervisor.update(
        now_s=2.21,
        present_position=9.0,
        requested_position=12.0,
        policy_requested_position=40.0,
        load_raw=240,
        current_raw=25,
    )
    assert released["event"] == "contact_released"
    assert released["latched"] is False
    assert released["guarded_position"] == 10.0


def test_gripper_supervisor_rejects_empty_close_baseline() -> None:
    supervisor = GripperContactSupervisor(
        minimum_position=7.0,
        minimum_load_percent=15.0,
        minimum_current_raw=15,
        confirmation_s=0.3,
        hold_offset=1.25,
        release_position=20.0,
        release_confirmation_s=0.2,
        maximum_hold_s=15.0,
    )
    state = supervisor.update(
        now_s=1.0,
        present_position=5.2,
        requested_position=5.0,
        policy_requested_position=5.0,
        load_raw=28,
        current_raw=1,
    )
    assert state["contact_signal"] is False
    assert state["latched"] is False


def test_action_dict_rejects_non_finite_and_dimension_mismatch() -> None:
    assert action_dict(["a", "b"], [1.0, 2.0]) == {"a": 1.0, "b": 2.0}
    with pytest.raises(ValueError, match="equal length"):
        action_dict(["a"], [1.0, 2.0])
    with pytest.raises(ValueError, match="non-finite"):
        action_dict(["a"], [float("nan")])


def test_total_travel_violations_uses_gripper_limit() -> None:
    start = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 0.0,
    }
    current = dict(start)
    current["shoulder_lift"] = -12.1
    current["gripper"] = 23.9
    assert total_travel_violations(start, current, 12.0, 24.0) == {
        "shoulder_lift": pytest.approx(-12.1)
    }


def test_total_travel_allows_only_existing_tracking_slack() -> None:
    start = {joint: 0.0 for joint in (
        "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "gripper"
    )}
    current = dict(start)
    current["elbow_flex"] = -70.2
    assert total_travel_violations(
        start, current, 70.0, 60.0, arm_feedback_slack=4.0
    ) == {}
    current["elbow_flex"] = -74.1
    assert total_travel_violations(
        start, current, 70.0, 60.0, arm_feedback_slack=4.0
    ) == {"elbow_flex": pytest.approx(-74.1)}


def test_total_envelope_clamps_command_before_transmission() -> None:
    start = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "gripper": 5.0,
    }
    command = {
        "shoulder_pan": 12.5,
        "shoulder_lift": -13.0,
        "elbow_flex": 1.0,
        "wrist_flex": 0.0,
        "gripper": -30.0,
    }
    bounded, joints = clamp_position_to_total_envelope(command, start, 12.0, 24.0)
    assert bounded == {
        "shoulder_pan": 12.0,
        "shoulder_lift": -12.0,
        "elbow_flex": 1.0,
        "wrist_flex": 0.0,
        "gripper": -19.0,
    }
    assert joints == ["shoulder_pan", "shoulder_lift", "gripper"]


def test_elbow_can_use_a_separate_total_travel_limit() -> None:
    start = {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 95.0,
        "wrist_flex": 0.0,
        "gripper": 0.0,
    }
    command = dict(start)
    command["shoulder_pan"] = -110.0
    command["elbow_flex"] = -25.0
    bounded, joints = clamp_position_to_total_envelope(
        command,
        start,
        arm_limit=100.0,
        gripper_limit=60.0,
        elbow_limit=125.0,
    )
    assert bounded["shoulder_pan"] == -100.0
    assert bounded["elbow_flex"] == -25.0
    assert joints == ["shoulder_pan"]


def test_rollout_guard_slews_command_and_bounds_feedback_error() -> None:
    guarded, reasons = rollout_guarded_action(
        predicted=[70.0, 5.0, 80.0],
        action_names=["elbow_flex.pos", "wrist_roll.vel_deg_s", "gripper.pos"],
        action_minimum=[-100.0, -8.0, 0.0],
        action_maximum=[100.0, 8.0, 100.0],
        previous_command={"elbow_flex": 95.0, "gripper": 5.0},
        feedback={"elbow_flex": 95.0, "gripper": 5.0},
        arm_step=1.0,
        gripper_step=2.0,
        wrist_speed_limit=1.0,
        arm_tracking_limit=4.0,
        gripper_tracking_limit=8.0,
    )
    assert guarded == {
        "elbow_flex.pos": 94.0,
        "wrist_roll.vel_deg_s": 1.0,
        "gripper.pos": 7.0,
    }
    assert reasons == {
        "elbow_flex.pos": ["command_slew"],
        "wrist_roll.vel_deg_s": ["wrist_speed"],
        "gripper.pos": ["command_slew"],
    }

    guarded, reasons = rollout_guarded_action(
        predicted=[70.0],
        action_names=["elbow_flex.pos"],
        action_minimum=[-100.0],
        action_maximum=[100.0],
        previous_command={"elbow_flex": 91.0},
        feedback={"elbow_flex": 95.0},
        arm_step=1.0,
        gripper_step=2.0,
        wrist_speed_limit=1.0,
        arm_tracking_limit=4.0,
        gripper_tracking_limit=8.0,
    )
    assert guarded == {"elbow_flex.pos": 91.0}
    assert reasons == {
        "elbow_flex.pos": ["command_slew", "tracking_envelope"]
    }


def test_position_action_bounds_intersect_observed_state_support() -> None:
    minimum, maximum = intersect_position_action_with_state_bounds(
        action_names=["shoulder_lift.pos", "wrist_roll.vel_deg_s"],
        action_minimum=[-30.0, -8.0],
        action_maximum=[30.0, 8.0],
        state_names=["shoulder_lift.pos", "wrist_roll.pos"],
        state_minimum=[-15.0, 20.0],
        state_maximum=[25.0, 40.0],
    )
    assert minimum == [-15.0, -8.0]
    assert maximum == [25.0, 8.0]


def test_chunk_summary_uses_next_chunk_state_as_boundary() -> None:
    def record(step: int, elbow: float, guarded: bool = False) -> dict:
        state = {
            "shoulder_pan": 0.0,
            "shoulder_lift": 0.0,
            "elbow_flex": elbow,
            "wrist_flex": 0.0,
            "wrist_roll": 0.0,
            "gripper": 0.0,
        }
        return {
            "step": step,
            "state": state,
            "predicted": {"elbow_flex.pos": elbow - 1.0},
            "command": {"elbow_flex.pos": elbow - 0.5},
            "guard_reasons": (
                {"elbow_flex.pos": ["command_slew"]} if guarded else {}
            ),
        }

    trace = [
        record(0, 10.0, guarded=True),
        record(1, 9.0),
        record(2, 8.0),
        record(3, 7.0),
    ]
    final_state = dict(trace[-1]["state"])
    final_state["elbow_flex"] = 6.0
    summaries = summarize_policy_chunks(trace, 2, final_state)

    assert len(summaries) == 2
    assert summaries[0]["steps"] == [0, 1]
    assert summaries[0]["end_state"]["elbow_flex"] == 8.0
    assert summaries[0]["state_delta"]["elbow_flex"] == -2.0
    assert summaries[0]["guard_reason_counts"] == {"command_slew": 1}
    assert summaries[1]["end_state"]["elbow_flex"] == 6.0


def test_wrist_state_has_separate_recovery_tolerance() -> None:
    clamped, outside = clamp_rollout_live_state(
        values=[-1.0, 24.4],
        minimum=[-2.0, 26.6],
        maximum=[2.0, 32.7],
        names=["elbow_flex.pos", "wrist_roll.pos"],
        default_tolerance=2.0,
        wrist_tolerance=8.0,
    )
    assert clamped == [-1.0, 26.6]
    assert outside[1] == pytest.approx(2.2)

    with pytest.raises(ValueError, match="elbow_flex.pos"):
        clamp_rollout_live_state(
            values=[-4.1, 30.0],
            minimum=[-2.0, 26.6],
            maximum=[2.0, 32.7],
            names=["elbow_flex.pos", "wrist_roll.pos"],
            default_tolerance=2.0,
            wrist_tolerance=8.0,
        )


def test_wrist_support_guard_blocks_outward_motion_and_recovers() -> None:
    assert keep_wrist_velocity_inside_state_support(
        -0.2, 24.4, 26.6, 32.7, 0.75, 0.5
    ) == (0.5, "wrist_support_recovery")
    assert keep_wrist_velocity_inside_state_support(
        -0.2, 26.8, 26.6, 32.7, 0.75, 0.5
    ) == (0.0, "wrist_support_margin")
    assert keep_wrist_velocity_inside_state_support(
        0.2, 30.0, 26.6, 32.7, 0.75, 0.5
    ) == (0.2, None)
