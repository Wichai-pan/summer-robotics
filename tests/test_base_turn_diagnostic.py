import pytest

from tools.base_turn_diagnostic import direction_sign, parse_args, validate_args


def test_direction_matches_documented_keyboard_convention() -> None:
    assert direction_sign("left") == 1.0
    assert direction_sign("right") == -1.0


def test_turn_target_cannot_exceed_open_space_first_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["base_turn_diagnostic.py", "--target-deg", "91"])
    with pytest.raises(ValueError, match="target-deg"):
        validate_args(parse_args())


def test_turn_drift_bound_cannot_be_relaxed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["base_turn_diagnostic.py", "--max-translation-m", "0.06"])
    with pytest.raises(ValueError, match="max-translation"):
        validate_args(parse_args())
