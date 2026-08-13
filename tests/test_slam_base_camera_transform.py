import json
from pathlib import Path

from tools.slam_base_camera_transform import (
    Transform,
    compose_transforms,
    invert_transform,
    parse_transform_config,
)


def write_config(path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {
        "schema": "forestbridge/slam/base-camera-transform/v1",
        "status": "candidate",
        "parent_frame": "base_link",
        "child_frame": "camera_link",
        "unit": "m",
        "translation_m": [0.1, 0.2, 0.3],
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "source_files": ["measured.txt"],
        "gimbal_reference_raw": {"7": 4062, "8": 2284},
        "measurement_notes": "measured fixture",
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_candidate_transform_parses(tmp_path: Path) -> None:
    transform = parse_transform_config(write_config(tmp_path / "candidate.yaml"), require_live=True)

    assert transform == Transform("base_link", "camera_link", (0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 1.0))


def test_project_candidate_preserves_measured_forward_pose() -> None:
    config = Path(__file__).parents[1] / "configs" / "slam" / "base_to_gemini_candidate.yaml"

    transform = parse_transform_config(config, require_live=True)

    assert transform == Transform(
        "base_link",
        "camera_link",
        (-0.04913, 0.025, 1.1825),
        (0.0, 0.0, 0.0, 1.0),
    )


def test_invalid_candidate_is_rejected(tmp_path: Path) -> None:
    cases = [
        ({"unit": "mm"}, "unit"),
        ({"translation_m": [0.0, 0.0]}, "translation_m"),
        ({"translation_m": [float("nan"), 0.0, 0.0]}, "finite"),
        ({"rotation_xyzw": [0.0, 0.0, 0.0, 0.0]}, "zero"),
        ({"rotation_xyzw": [0.0, 0.0, 0.0, 2.0]}, "normalized"),
        ({"parent_frame": "camera_link", "child_frame": "base_link"}, "parent_frame"),
        ({"gimbal_reference_raw": {"7": "4062", "8": 2284}}, "encoder raw"),
    ]
    for overrides, message in cases:
        try:
            parse_transform_config(write_config(tmp_path / "bad.yaml", **overrides), require_live=True)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError(f"invalid candidate accepted: {overrides}")


def test_unresolved_is_dry_run_only(tmp_path: Path) -> None:
    config = write_config(tmp_path / "unresolved.yaml", status="unresolved")

    assert parse_transform_config(config) is None
    try:
        parse_transform_config(config, require_live=True)
    except ValueError as error:
        assert "unresolved" in str(error)
    else:
        raise AssertionError("unresolved transform was accepted for live mode")


def test_transform_inverse_and_composition_produce_identity() -> None:
    transform = Transform("base_link", "camera_link", (0.1, -0.2, 0.3), (0.0, 0.0, 0.0, 1.0))
    identity = compose_transforms(transform, invert_transform(transform))

    assert identity.parent_frame == identity.child_frame == "base_link"
    assert identity.translation_m == (0.0, 0.0, 0.0)
    assert identity.rotation_xyzw == (0.0, 0.0, 0.0, 1.0)
