from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "fit_black_arm_eye_to_hand.py"
SPEC = importlib.util.spec_from_file_location("eye_to_hand_fit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fit_module
SPEC.loader.exec_module(fit_module)


class EyeToHandFitTest(unittest.TestCase):
    def test_recovers_synthetic_urdf_marker_geometry(self) -> None:
        chain = fit_module.load_urdf_chain(
            ROOT / "simulation" / "Maniskill" / "assets" / "xlerobot" / "xlerobot.urdf"
        )
        rng = np.random.default_rng(7)
        measured = rng.uniform(
            low=[-35.0, -10.0, -175.0, -80.0, -170.0],
            high=[35.0, 45.0, -105.0, 150.0, 170.0],
            size=(14, 5),
        )
        signs = np.asarray([-1.0, -1.0, 1.0, 1.0, -1.0])
        true_parameters = np.r_[
            np.radians([20.0, -150.0, -100.0]),
            np.asarray([-0.008, -0.025, 0.04]),
        ]
        base_points = fit_module.predict_base_points(measured, signs, true_parameters, chain)
        rotation = Rotation.from_euler("xyz", [0.2, -0.3, 0.7]).as_matrix()
        translation = np.asarray([-0.12, 0.20, 0.09])
        observed = (rotation @ base_points.T).T + translation

        fitted = fit_module.fit_one_sign_model(
            measured,
            observed,
            signs,
            chain,
            starts=8,
            rng=np.random.default_rng(11),
        )
        prediction = fit_module.apply_camera_transform(
            fit_module.predict_base_points(measured, signs, fitted["parameters"], chain),
            fitted,
        )
        point_rmse = np.sqrt(np.mean(np.sum((prediction - observed) ** 2, axis=1)))
        self.assertLess(point_rmse, 1e-5)


if __name__ == "__main__":
    unittest.main()
