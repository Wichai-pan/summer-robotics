import cv2
import numpy as np

from perception import CameraIntrinsics, DetectorConfig, detect_blue_cylinder


def test_blue_cylinder_backprojection_and_radius_compensation():
    height, width = 480, 640
    bgr = np.zeros((height, width, 3), dtype=np.uint8)
    depth = np.full((height, width), np.nan, dtype=np.float32)
    cv2.rectangle(bgr, (350, 190), (410, 310), (255, 80, 20), -1)
    depth[190:311, 350:411] = 0.800
    # Add an unrelated outlier that robust filtering must ignore.
    depth[200:205, 355:360] = 2.0
    intr = CameraIntrinsics(width, height, 600.0, 600.0, 319.5, 239.5)
    cfg = DetectorConfig(min_area_px=100, cylinder_radius_m=0.018)

    detection, mask = detect_blue_cylinder(bgr, depth, intr, cfg)

    assert detection is not None
    assert np.count_nonzero(mask) > 7000
    assert detection.surface_centroid_m[0] > 0
    assert abs(detection.median_depth_m - 0.8) < 1e-6
    assert detection.cylinder_center_estimate_m[2] > detection.surface_centroid_m[2]
    assert detection.valid_depth_pixels > 7000


def test_no_blue_returns_none():
    bgr = np.zeros((100, 120, 3), dtype=np.uint8)
    depth = np.ones((100, 120), dtype=np.float32)
    detection, mask = detect_blue_cylinder(
        bgr, depth, CameraIntrinsics.estimated(120, 100), DetectorConfig(min_area_px=20)
    )
    assert detection is None
    assert not np.any(mask)
