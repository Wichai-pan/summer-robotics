#!/usr/bin/env python3
"""Fit black-arm eye-to-hand geometry from paired encoder/RGB-D samples.

This is an offline diagnostic tool.  It never opens a camera, serial port, or
motor bus, and its output is deliberately marked motion_locked.

Model:

    p_camera = T_camera_from_arm_base @ FK_URDF(q_measured) @ p_marker_in_jaw

The five joint directions are enumerated as +/-1.  Shoulder-pan and wrist-roll
zero offsets are fixed as gauge choices: the former is inseparable from the
free camera rotation, and the latter from the unknown marker point rotation.
The lift, elbow, and wrist-flex zero offsets and the fixed marker point are
fitted.  For every nonlinear proposal, the best rigid camera transform is
recovered by Kabsch alignment.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
URDF_JOINTS = {
    "shoulder_pan": "Rotation_2",
    "shoulder_lift": "Pitch_2",
    "elbow_flex": "Elbow_2",
    "wrist_flex": "Wrist_Pitch_2",
    "wrist_roll": "Wrist_Roll_2",
}
OFFSET_JOINTS = ("shoulder_lift", "elbow_flex", "wrist_flex")


@dataclass(frozen=True)
class JointGeometry:
    origin: np.ndarray
    axis: np.ndarray


def transform(rotation: np.ndarray | None = None, translation: np.ndarray | None = None) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    if rotation is not None:
        result[:3, :3] = rotation
    if translation is not None:
        result[:3, 3] = translation
    return result


def parse_vector(text: str | None, default: str) -> np.ndarray:
    return np.asarray([float(value) for value in (text or default).split()], dtype=np.float64)


def load_urdf_chain(path: Path) -> dict[str, JointGeometry]:
    root = ET.parse(path).getroot()
    xml_joints = {element.attrib["name"]: element for element in root.findall("joint")}
    chain: dict[str, JointGeometry] = {}
    for name in JOINTS:
        urdf_name = URDF_JOINTS[name]
        element = xml_joints.get(urdf_name)
        if element is None:
            raise SystemExit(f"URDF missing joint {urdf_name}")
        origin_element = element.find("origin")
        axis_element = element.find("axis")
        if origin_element is None or axis_element is None:
            raise SystemExit(f"URDF joint {urdf_name} lacks origin/axis")
        xyz = parse_vector(origin_element.attrib.get("xyz"), "0 0 0")
        rpy = parse_vector(origin_element.attrib.get("rpy"), "0 0 0")
        axis = parse_vector(axis_element.attrib.get("xyz"), "1 0 0")
        axis /= np.linalg.norm(axis)
        origin = transform(Rotation.from_euler("xyz", rpy).as_matrix(), xyz)
        chain[name] = JointGeometry(origin=origin, axis=axis)
    return chain


def load_samples(path: Path) -> list[dict]:
    samples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(samples) < 7:
        raise SystemExit(f"Need at least 7 samples; found {len(samples)}")
    labels = [str(sample["label"]) for sample in samples]
    if len(labels) != len(set(labels)):
        raise SystemExit("Sample labels must be unique")
    return samples


def fk_marker(
    measured_deg: np.ndarray,
    signs: np.ndarray,
    offsets_rad: np.ndarray,
    marker_jaw_m: np.ndarray,
    chain: dict[str, JointGeometry],
) -> np.ndarray:
    offsets = dict.fromkeys(JOINTS, 0.0)
    offsets.update(dict(zip(OFFSET_JOINTS, offsets_rad, strict=True)))
    pose = np.eye(4, dtype=np.float64)
    for index, name in enumerate(JOINTS):
        geometry = chain[name]
        angle = signs[index] * math.radians(float(measured_deg[index])) + offsets[name]
        joint_rotation = Rotation.from_rotvec(geometry.axis * angle).as_matrix()
        pose = pose @ geometry.origin @ transform(joint_rotation)
    return (pose @ np.r_[marker_jaw_m, 1.0])[:3]


def rigid_alignment(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    covariance = (source - source_mean).T @ (target - target_mean)
    u, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = target_mean - rotation @ source_mean
    return rotation, translation


def predict_base_points(
    measured: np.ndarray,
    signs: np.ndarray,
    parameters: np.ndarray,
    chain: dict[str, JointGeometry],
) -> np.ndarray:
    offsets = parameters[:3]
    marker = parameters[3:6]
    return np.asarray([fk_marker(q, signs, offsets, marker, chain) for q in measured])


def fit_one_sign_model(
    measured: np.ndarray,
    observed_camera: np.ndarray,
    signs: np.ndarray,
    chain: dict[str, JointGeometry],
    starts: int,
    rng: np.random.Generator,
) -> dict:
    lower = np.r_[np.full(3, -math.pi), np.full(3, -0.20)]
    upper = np.r_[np.full(3, math.pi), np.full(3, 0.20)]
    initial_marker = np.asarray([0.01, -0.097, 0.0])
    best = None

    def residual(parameters: np.ndarray) -> np.ndarray:
        base_points = predict_base_points(measured, signs, parameters, chain)
        rotation, translation = rigid_alignment(base_points, observed_camera)
        prediction = (rotation @ base_points.T).T + translation
        return (prediction - observed_camera).ravel()

    for start in range(starts):
        if start == 0:
            initial = np.r_[np.zeros(3), initial_marker]
        else:
            initial = np.r_[rng.uniform(-math.pi, math.pi, 3), initial_marker + rng.normal(0, 0.04, 3)]
            initial = np.clip(initial, lower + 1e-8, upper - 1e-8)
        result = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            loss="soft_l1",
            f_scale=0.003,
            max_nfev=2500,
            xtol=1e-11,
            ftol=1e-11,
            gtol=1e-11,
        )
        squared_error = float(np.sum(residual(result.x) ** 2))
        if best is None or squared_error < best["squared_error"]:
            base_points = predict_base_points(measured, signs, result.x, chain)
            rotation, translation = rigid_alignment(base_points, observed_camera)
            best = {
                "parameters": result.x.copy(),
                "rotation": rotation,
                "translation": translation,
                "squared_error": squared_error,
                "success": bool(result.success),
                "nfev": int(result.nfev),
            }
    assert best is not None
    return best


def apply_camera_transform(points: np.ndarray, fit: dict) -> np.ndarray:
    return (fit["rotation"] @ points.T).T + fit["translation"]


def transform_matrix(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return transform(rotation, translation)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples",
        type=Path,
        default=Path("calibration/black_arm_eye_to_hand_samples.jsonl"),
    )
    parser.add_argument(
        "--urdf",
        type=Path,
        default=Path("simulation/Maniskill/assets/xlerobot/xlerobot.urdf"),
    )
    parser.add_argument("--holdout-label", default="pose_09_multi_joint_roll")
    parser.add_argument("--starts", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("calibration/black_arm_eye_to_hand_fit.json"),
    )
    args = parser.parse_args()
    if args.starts < 1:
        raise SystemExit("--starts must be positive")

    samples = load_samples(args.samples)
    chain = load_urdf_chain(args.urdf)
    labels = [str(sample["label"]) for sample in samples]
    try:
        holdout_index = labels.index(args.holdout_label)
    except ValueError as exc:
        raise SystemExit(f"Unknown holdout label: {args.holdout_label}") from exc

    measured = np.asarray([[sample["measured_encoder"][joint] for joint in JOINTS] for sample in samples])
    observed = np.asarray([sample["marker_camera_xyz_m"] for sample in samples])
    train_mask = np.ones(len(samples), dtype=bool)
    train_mask[holdout_index] = False
    measured_train = measured[train_mask]
    observed_train = observed[train_mask]

    print(f"Offline fit: {int(train_mask.sum())} training samples; holdout={args.holdout_label}")
    print("Enumerating 32 joint-direction conventions; no hardware is opened.")
    rng = np.random.default_rng(args.seed)
    candidates = []
    for sign_tuple in itertools.product((-1.0, 1.0), repeat=len(JOINTS)):
        signs = np.asarray(sign_tuple)
        fit = fit_one_sign_model(measured_train, observed_train, signs, chain, args.starts, rng)
        train_rmse = math.sqrt(fit["squared_error"] / measured_train.shape[0])
        candidates.append((train_rmse, signs, fit))
    candidates.sort(key=lambda item: item[0])
    train_rmse, signs, fit = candidates[0]
    candidate_summary = [
        {
            "train_rmse_m": float(candidate_rmse),
            "joint_signs": dict(zip(JOINTS, candidate_signs.astype(int).tolist(), strict=True)),
        }
        for candidate_rmse, candidate_signs, _ in candidates[:5]
    ]

    train_base = predict_base_points(measured_train, signs, fit["parameters"], chain)
    train_prediction = apply_camera_transform(train_base, fit)
    train_errors = np.linalg.norm(train_prediction - observed_train, axis=1)
    holdout_base = predict_base_points(measured[[holdout_index]], signs, fit["parameters"], chain)
    holdout_prediction = apply_camera_transform(holdout_base, fit)[0]
    holdout_error = float(np.linalg.norm(holdout_prediction - observed[holdout_index]))

    camera_from_arm = transform_matrix(fit["rotation"], fit["translation"])
    arm_from_camera = np.linalg.inv(camera_from_arm)
    parameters = fit["parameters"]
    offsets_deg = dict(zip(OFFSET_JOINTS, np.degrees(parameters[:3]).tolist(), strict=True))
    sign_map = dict(zip(JOINTS, signs.astype(int).tolist(), strict=True))

    result = {
        "schema": "black_arm_eye_to_hand_fit/v1",
        "status": "diagnostic_only",
        "motion_locked": True,
        "model": "URDF FK + joint signs + 3 identifiable zero offsets + jaw marker + rigid camera extrinsic",
        "gauge_choices": {
            "shoulder_pan_offset_deg": 0.0,
            "wrist_roll_offset_deg": 0.0,
            "reason": "These offsets are not separately identifiable from camera rotation / marker orientation.",
        },
        "training_labels": [label for i, label in enumerate(labels) if i != holdout_index],
        "holdout_label": args.holdout_label,
        "joint_signs": sign_map,
        "fitted_joint_offsets_deg": offsets_deg,
        "marker_in_fixed_jaw_m": parameters[3:6].tolist(),
        "camera_from_arm_base_4x4": camera_from_arm.tolist(),
        "arm_base_from_camera_4x4": arm_from_camera.tolist(),
        "train_rmse_m": float(train_rmse),
        "train_errors_m": {
            label: float(error)
            for label, error in zip([label for i, label in enumerate(labels) if i != holdout_index], train_errors, strict=True)
        },
        "holdout_observed_camera_m": observed[holdout_index].tolist(),
        "holdout_predicted_camera_m": holdout_prediction.tolist(),
        "holdout_error_m": holdout_error,
        "fit_settings": {"starts_per_sign": args.starts, "seed": args.seed},
        "top_direction_candidates": candidate_summary,
        "notes": [
            "Do not copy this matrix into a motor-execution config until holdout and repeatability gates pass.",
            "Measured encoder coordinates, not legacy SAVED_TARGET coordinates, were used for geometry.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("best joint signs:", sign_map)
    print(
        "top-5 direction train RMSE (mm):",
        [round(candidate["train_rmse_m"] * 1000, 3) for candidate in candidate_summary],
    )
    print("fitted offsets (deg):", {key: round(value, 3) for key, value in offsets_deg.items()})
    print("marker in Fixed_Jaw (m):", np.round(parameters[3:6], 5).tolist())
    print(f"training point RMSE: {train_rmse * 1000:.2f} mm")
    print(f"holdout error ({args.holdout_label}): {holdout_error * 1000:.2f} mm")
    print(f"saved diagnostic fit: {args.output}")
    if holdout_error > 0.020:
        print("RESULT: FAIL (>20 mm holdout error). Do not use for physical IK.")
        return 2
    print("RESULT: provisional geometric fit; repeatability checks are still required before physical IK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
