from tools.base_stop_diagnostic import STOP_VELOCITY_EPS_RAW, stop_readback_confirmed


def torque_off_observation(*, torque: int, velocity: int = 0) -> dict[str, object]:
    return {
        "phase": "torque_off_observe",
        "wheels": {
            str(motor_id): {
                "goal_velocity_raw": 0,
                "present_velocity_signed_raw": velocity,
                "torque_enable": torque,
            }
            for motor_id in (7, 8, 9)
        },
    }


def test_stop_confirmation_rejects_old_false_positive_with_torque_still_enabled() -> None:
    # This is the exact unsafe state observed in the 2026-08-23 forward pulse:
    # velocity/goal looked idle but all wheels still reported Torque_Enable=1.
    samples = [torque_off_observation(torque=1) for _ in range(3)]

    assert stop_readback_confirmed(samples) is False


def test_stop_confirmation_accepts_torque_off_idle_velocity_feedback() -> None:
    samples = [
        torque_off_observation(torque=0, velocity=-50),
        torque_off_observation(torque=0, velocity=0),
        torque_off_observation(torque=0, velocity=STOP_VELOCITY_EPS_RAW),
    ]

    assert stop_readback_confirmed(samples) is True
