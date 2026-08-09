"""Blue-cylinder perception on registered BGR and metric depth images.

Coordinates follow the ROS optical convention used by Orbbec:
    +x right, +y down, +z forward, origin at the color camera optical center.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def estimated(cls, width: int, height: int, hfov_deg: float = 70.0, vfov_deg: float = 55.0):
        """Offline-only fallback based on Gemini 335 RGB 4:3 nominal FOV."""
        fx = width / (2.0 * np.tan(np.deg2rad(hfov_deg) / 2.0))
        fy = height / (2.0 * np.tan(np.deg2rad(vfov_deg) / 2.0))
        return cls(width, height, float(fx), float(fy), (width - 1) / 2.0, (height - 1) / 2.0)


@dataclass
class CylinderDetection:
    pixel_centroid_uv: tuple[float, float]
    surface_centroid_m: tuple[float, float, float]
    cylinder_center_estimate_m: tuple[float, float, float]
    range_m: float
    median_depth_m: float
    depth_mad_m: float
    mask_pixels: int
    valid_depth_pixels: int
    bounding_box_xywh: tuple[int, int, int, int]
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DetectorConfig:
    # OpenCV hue is [0, 179]. These broad defaults cover vivid dark/light blue.
    hsv_lower: tuple[int, int, int] = (90, 70, 35)
    hsv_upper: tuple[int, int, int] = (140, 255, 255)
    min_area_px: int = 250
    min_depth_m: float = 0.10
    max_depth_m: float = 3.0
    morphology_kernel_px: int = 5
    depth_mad_scale: float = 3.5
    cylinder_radius_m: float = 0.018


def segment_blue(bgr: np.ndarray, config: DetectorConfig) -> np.ndarray:
    """Return a cleaned uint8 mask for the largest plausible blue component."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.asarray(config.hsv_lower), np.asarray(config.hsv_upper))
    k = max(1, int(config.morphology_kernel_px))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return np.zeros_like(mask)
    component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if int(stats[component, cv2.CC_STAT_AREA]) < config.min_area_px:
        return np.zeros_like(mask)
    return np.where(labels == component, 255, 0).astype(np.uint8)


def _robust_depth_selection(depth_m: np.ndarray, mask: np.ndarray, config: DetectorConfig) -> np.ndarray:
    valid = (
        (mask > 0)
        & np.isfinite(depth_m)
        & (depth_m >= config.min_depth_m)
        & (depth_m <= config.max_depth_m)
    )
    values = depth_m[valid]
    if values.size < 20:
        return valid
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    # Keep a small floor because quantized depth can have MAD == 0.
    tolerance = max(0.008, config.depth_mad_scale * 1.4826 * mad)
    return valid & (np.abs(depth_m - median) <= tolerance)


def detect_blue_cylinder(
    bgr: np.ndarray,
    depth_m: np.ndarray,
    intrinsics: CameraIntrinsics,
    config: Optional[DetectorConfig] = None,
) -> tuple[Optional[CylinderDetection], np.ndarray]:
    """Detect the blue component and back-project its robust depth points."""
    cfg = config or DetectorConfig()
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("bgr must have shape HxWx3")
    if depth_m.shape != bgr.shape[:2]:
        raise ValueError("depth must be aligned to color and have the same HxW shape")

    mask = segment_blue(bgr, cfg)
    mask_pixels = int(np.count_nonzero(mask))
    if mask_pixels < cfg.min_area_px:
        return None, mask

    selected = _robust_depth_selection(depth_m, mask, cfg)
    rows, cols = np.nonzero(selected)
    if rows.size < max(30, cfg.min_area_px // 8):
        return None, mask

    z = depth_m[rows, cols].astype(np.float64)
    x = (cols.astype(np.float64) - intrinsics.cx) * z / intrinsics.fx
    y = (rows.astype(np.float64) - intrinsics.cy) * z / intrinsics.fy
    points = np.column_stack((x, y, z))
    surface = np.median(points, axis=0)

    # The visible colored cloud lies mostly on the near surface. Move by the
    # known radius along the optical ray to approximate the solid's center.
    ray = surface / max(float(np.linalg.norm(surface)), 1e-9)
    center = surface + cfg.cylinder_radius_m * ray

    ys, xs = np.nonzero(mask)
    bbox = cv2.boundingRect(np.column_stack((xs, ys)).astype(np.int32))
    pixel = (float(np.median(cols)), float(np.median(rows)))
    depth_mad = float(np.median(np.abs(z - np.median(z))))
    depth_fraction = rows.size / max(mask_pixels, 1)
    compactness = min(1.0, mask_pixels / max(float(bbox[2] * bbox[3]), 1.0))
    confidence = float(np.clip(0.65 * depth_fraction + 0.35 * compactness, 0.0, 1.0))

    detection = CylinderDetection(
        pixel_centroid_uv=pixel,
        surface_centroid_m=tuple(float(v) for v in surface),
        cylinder_center_estimate_m=tuple(float(v) for v in center),
        range_m=float(np.linalg.norm(center)),
        median_depth_m=float(np.median(z)),
        depth_mad_m=depth_mad,
        mask_pixels=mask_pixels,
        valid_depth_pixels=int(rows.size),
        bounding_box_xywh=tuple(int(v) for v in bbox),
        confidence=confidence,
    )
    return detection, mask


def annotate(
    bgr: np.ndarray,
    mask: np.ndarray,
    detection: Optional[CylinderDetection],
    intrinsics: CameraIntrinsics,
    fps: float = 0.0,
) -> np.ndarray:
    """Draw mask, camera principal point, detection and metric diagnostics."""
    view = bgr.copy()
    blue_overlay = np.zeros_like(view)
    blue_overlay[:, :, 0] = mask
    view = cv2.addWeighted(view, 1.0, blue_overlay, 0.30, 0.0)
    principal = (int(round(intrinsics.cx)), int(round(intrinsics.cy)))
    cv2.drawMarker(view, principal, (0, 255, 255), cv2.MARKER_CROSS, 24, 2)
    cv2.putText(view, "camera optical center", (principal[0] + 10, principal[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(view, f"FPS {fps:4.1f}", (12, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (255, 255, 255), 2, cv2.LINE_AA)

    if detection is None:
        cv2.putText(view, "BLUE CYLINDER: NOT DETECTED", (12, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (40, 40, 255), 2, cv2.LINE_AA)
        return view

    x, y, w, h = detection.bounding_box_xywh
    u, v = detection.pixel_centroid_uv
    cv2.rectangle(view, (x, y), (x + w, y + h), (80, 255, 80), 2)
    cv2.drawMarker(view, (int(round(u)), int(round(v))), (80, 255, 80),
                   cv2.MARKER_CROSS, 22, 2)
    c = np.asarray(detection.cylinder_center_estimate_m) * 1000.0
    lines = [
        "BLUE CYLINDER DETECTED",
        f"center x(right)={c[0]:+.1f} mm",
        f"center y(down) ={c[1]:+.1f} mm",
        f"center z(fwd)  ={c[2]:+.1f} mm",
        f"range={detection.range_m*1000:.1f} mm  conf={detection.confidence:.2f}",
        f"depth MAD={detection.depth_mad_m*1000:.1f} mm  valid={detection.valid_depth_pixels}",
    ]
    for index, line in enumerate(lines):
        cv2.putText(view, line, (12, 52 + 25 * index), cv2.FONT_HERSHEY_SIMPLEX,
                    0.58, (80, 255, 80), 2, cv2.LINE_AA)
    return view
