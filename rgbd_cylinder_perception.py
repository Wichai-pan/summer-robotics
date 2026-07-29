# Copyright (c) 2026, XLeRobot Project Developers.
# SPDX-License-Identifier: BSD-3-Clause

"""Small RGB-D cylinder detector used by the deterministic pick demo.

The module deliberately has no Isaac Sim dependency.  It consumes registered
RGB and depth tensors, applies color segmentation, back-projects the selected
pixels, and estimates each vertical cylinder's geometric center in the robot
base frame.
"""

from dataclasses import dataclass

import torch


@dataclass
class CylinderDetection:
    """One color-segmented cylinder estimate in the robot base frame."""

    label: str
    centroid_b: torch.Tensor
    point_count: int
    median_depth: float
    top_point_count: int


def _as_rgb_255(rgb: torch.Tensor) -> torch.Tensor:
    """Return the first three image channels as float RGB in [0, 255]."""
    image = rgb[..., :3].to(dtype=torch.float32)
    if image.numel() and float(image.max()) <= 1.5:
        image = image * 255.0
    return image


def color_masks(rgb: torch.Tensor) -> dict[str, torch.Tensor]:
    """Segment the saturated blue and red task cylinders using RGB only."""
    image = _as_rgb_255(rgb)
    red, green, blue = image.unbind(dim=-1)
    return {
        "blue": (
            (blue > 85.0)
            & (blue > 1.12 * green)
            & (blue > 1.35 * red)
            & ((blue - torch.maximum(red, green)) > 25.0)
        ),
        "red": (
            (red > 100.0)
            & (red > 1.7 * green)
            & (red > 1.7 * blue)
            & ((red - torch.maximum(green, blue)) > 45.0)
        ),
    }


def _masked_points_in_base(
    mask: torch.Tensor,
    depth: torch.Tensor,
    intrinsics: torch.Tensor,
    camera_position_b: torch.Tensor,
    camera_rotation_b_ros: torch.Tensor,
    min_depth: float,
    max_depth: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Back-project masked pixels and transform ROS optical points to base."""
    depth_image = depth.squeeze(-1) if depth.ndim == 3 else depth
    valid = mask & torch.isfinite(depth_image) & (depth_image > min_depth) & (depth_image < max_depth)
    rows, cols = torch.nonzero(valid, as_tuple=True)
    if rows.numel() == 0:
        empty = torch.empty((0, 3), device=depth.device, dtype=torch.float32)
        return empty, torch.empty((0,), device=depth.device, dtype=torch.float32)

    z = depth_image[rows, cols].to(dtype=torch.float32)
    matrix = intrinsics.to(device=depth.device, dtype=torch.float32)
    x = (cols.to(dtype=torch.float32) - matrix[0, 2]) * z / matrix[0, 0]
    y = (rows.to(dtype=torch.float32) - matrix[1, 2]) * z / matrix[1, 1]
    points_camera = torch.stack((x, y, z), dim=-1)
    rotation = camera_rotation_b_ros.to(device=depth.device, dtype=torch.float32)
    position = camera_position_b.to(device=depth.device, dtype=torch.float32)
    points_base = points_camera @ rotation.transpose(0, 1) + position
    return points_base, z


def estimate_colored_cylinders(
    rgb: torch.Tensor,
    depth: torch.Tensor,
    intrinsics: torch.Tensor,
    camera_position_b: torch.Tensor,
    camera_rotation_b_ros: torch.Tensor,
    cylinder_height: float,
    min_pixels: int = 40,
    min_depth: float = 0.15,
    max_depth: float = 2.0,
) -> list[CylinderDetection]:
    """Estimate vertical-cylinder centers from RGB masks and a registered depth map.

    The upper portion of each colored cloud belongs to the visible top disk.
    Its median x/y is a robust center estimate; the known cylinder height moves
    the detected top surface down to the solid's geometric center.
    """
    detections: list[CylinderDetection] = []
    for label, mask in color_masks(rgb).items():
        points_b, point_depths = _masked_points_in_base(
            mask,
            depth,
            intrinsics,
            camera_position_b,
            camera_rotation_b_ros,
            min_depth,
            max_depth,
        )
        if points_b.shape[0] < min_pixels:
            continue

        # The top disk is planar while the visible side spans the full object
        # height.  Estimate the plane from an upper quantile, then use a narrow
        # metric band around it.  This is much less biased than averaging the
        # upper fraction of a heavily occluded side cloud.
        top_z = torch.quantile(points_b[:, 2], 0.95)
        top_points = points_b[torch.abs(points_b[:, 2] - top_z) <= 0.004]
        if top_points.shape[0] < max(10, min_pixels // 4):
            continue

        center_xy = torch.median(top_points[:, :2], dim=0).values
        top_z = torch.median(top_points[:, 2])
        centroid = torch.cat((center_xy, (top_z - 0.5 * cylinder_height).view(1)))
        detections.append(
            CylinderDetection(
                label=label,
                centroid_b=centroid,
                point_count=int(points_b.shape[0]),
                median_depth=float(torch.median(point_depths)),
                top_point_count=int(top_points.shape[0]),
            )
        )
    return detections


def select_nearest_detection(detections: list[CylinderDetection]) -> CylinderDetection:
    """Select the detected object with the smallest planar base-frame range."""
    if not detections:
        raise ValueError("No RGB-D cylinder detections were supplied.")
    return min(detections, key=lambda detection: float(torch.linalg.norm(detection.centroid_b[:2])))
