from act_checkpoint_dry_run import bounds_status


def test_bounds_status_is_inclusive_and_dimensionwise() -> None:
    assert bounds_status([0.0, 2.0, 5.0], [0.0, 1.0, 3.0], [1.0, 2.0, 4.0]) == [
        True,
        True,
        False,
    ]
