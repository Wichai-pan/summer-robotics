from wrist_roll_velocity_follow import velocity_command_raw, wrapped_tick_delta


def test_wrapped_tick_delta_takes_short_path_across_zero() -> None:
    assert wrapped_tick_delta(3, 4090) == 9
    assert wrapped_tick_delta(4090, 3) == -9


def test_wrapped_tick_delta_preserves_ordinary_direction() -> None:
    assert wrapped_tick_delta(1200, 1100) == 100
    assert wrapped_tick_delta(1100, 1200) == -100


def test_velocity_command_has_deadband_and_speed_cap() -> None:
    assert velocity_command_raw(1.0, 1.5, 8.0, 1.5) == 0
    assert velocity_command_raw(100.0, 1.5, 8.0, 1.5) == 91
    assert velocity_command_raw(-100.0, 1.5, 8.0, 1.5) == -91


def test_velocity_command_follows_error_sign() -> None:
    assert velocity_command_raw(2.0, 1.5, 8.0, 1.5) > 0
    assert velocity_command_raw(-2.0, 1.5, 8.0, 1.5) < 0
