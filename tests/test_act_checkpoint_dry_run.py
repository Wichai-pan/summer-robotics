from act_checkpoint_dry_run import bounds_status, parse_frame_indices


def test_bounds_status_is_inclusive_and_dimensionwise() -> None:
    assert bounds_status([0.0, 2.0, 5.0], [0.0, 1.0, 3.0], [1.0, 2.0, 4.0]) == [
        True,
        True,
        False,
    ]


def test_parse_frame_indices() -> None:
    assert parse_frame_indices(None, 7) == [7]
    assert parse_frame_indices("0, 12,24", 7) == [0, 12, 24]
