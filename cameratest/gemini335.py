"""Small Orbbec SDK V2 adapter for aligned Gemini 335 RGB-D frames."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import cv2
import numpy as np

from perception import CameraIntrinsics


def _sdk():
    try:
        import pyorbbecsdk as ob
    except ImportError as exc:
        raise RuntimeError(
            "Orbbec SDK is missing. Install it with: pip install --upgrade pyorbbecsdk2"
        ) from exc
    return ob


def _read_member(obj: Any, names: tuple[str, ...]) -> str | None:
    for name in names:
        try:
            value = getattr(obj, name)
            return str(value() if callable(value) else value)
        except Exception:
            pass
    return None


def color_frame_to_bgr(frame, ob) -> np.ndarray | None:
    width, height = frame.get_width(), frame.get_height()
    raw = frame.get_data()
    data = np.asarray(raw, dtype=np.uint8).reshape(-1) if isinstance(raw, np.ndarray) else np.frombuffer(raw, np.uint8)
    fmt = frame.get_format()
    if fmt == ob.OBFormat.RGB:
        return cv2.cvtColor(np.resize(data, (height, width, 3)), cv2.COLOR_RGB2BGR)
    if fmt == ob.OBFormat.BGR:
        return np.resize(data, (height, width, 3)).copy()
    if fmt == ob.OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if fmt == ob.OBFormat.YUYV:
        return cv2.cvtColor(np.resize(data, (height, width, 2)), cv2.COLOR_YUV2BGR_YUY2)
    return None


class Gemini335Camera:
    """Capture depth registered into the RGB image and expose factory calibration."""

    def __init__(self, timeout_ms: int = 1000):
        self.ob = _sdk()
        self.timeout_ms = timeout_ms
        self.pipeline = None
        self.align_filter = None
        self.camera_param = None
        self.intrinsics = None
        self.device_info = {}

    def start(self) -> CameraIntrinsics:
        ob = self.ob
        context = ob.Context()
        devices = context.query_devices()
        if devices.get_count() == 0:
            raise RuntimeError("No Orbbec camera found. Check USB cable/power and Orbbec Viewer.")

        self.pipeline = ob.Pipeline()
        config = ob.Config()
        colors = self.pipeline.get_stream_profile_list(ob.OBSensorType.COLOR_SENSOR)
        try:
            color_profile = colors.get_video_stream_profile(0, 0, ob.OBFormat.RGB, 0)
        except Exception:
            color_profile = colors.get_default_video_stream_profile()
        depths = self.pipeline.get_stream_profile_list(ob.OBSensorType.DEPTH_SENSOR)
        depth_profile = depths.get_default_video_stream_profile()
        config.enable_stream(color_profile)
        config.enable_stream(depth_profile)
        if hasattr(ob, "OBFrameAggregateOutputMode"):
            config.set_frame_aggregate_output_mode(ob.OBFrameAggregateOutputMode.FULL_FRAME_REQUIRE)
        try:
            self.pipeline.enable_frame_sync()
        except Exception:
            pass
        self.align_filter = ob.AlignFilter(align_to_stream=ob.OBStreamType.COLOR_STREAM)
        self.pipeline.start(config)

        # A delivered frameset ensures the active profile's calibration is resolved.
        for _ in range(30):
            frames = self.pipeline.wait_for_frames(self.timeout_ms)
            if frames:
                break
        else:
            self.stop()
            raise RuntimeError("Camera opened but no RGB-D frames arrived.")

        self.camera_param = self.pipeline.get_camera_param()
        intr = self.camera_param.rgb_intrinsic
        self.intrinsics = CameraIntrinsics(
            int(intr.width), int(intr.height), float(intr.fx), float(intr.fy),
            float(intr.cx), float(intr.cy)
        )
        try:
            info = self.pipeline.get_device().get_device_info()
            self.device_info = {
                "name": _read_member(info, ("get_name", "name")),
                "serial_number": _read_member(info, ("get_serial_number", "serial_number")),
                "firmware_version": _read_member(info, ("get_firmware_version", "firmware_version")),
                "connection_type": _read_member(info, ("get_connection_type", "connection_type")),
            }
        except Exception:
            self.device_info = {}
        return self.intrinsics

    def read(self) -> tuple[np.ndarray, np.ndarray] | None:
        frames = self.pipeline.wait_for_frames(self.timeout_ms)
        if not frames:
            return None
        aligned = self.align_filter.process(frames)
        if not aligned:
            return None
        color_frame = aligned.get_color_frame()
        depth_frame = aligned.get_depth_frame()
        if not color_frame or not depth_frame:
            return None
        bgr = color_frame_to_bgr(color_frame, self.ob)
        if bgr is None:
            raise RuntimeError(f"Unsupported color format: {color_frame.get_format()}")
        if bgr.shape[:2] != (self.intrinsics.height, self.intrinsics.width):
            raise RuntimeError(
                f"RGB frame {bgr.shape[1]}x{bgr.shape[0]} does not match factory intrinsics "
                f"{self.intrinsics.width}x{self.intrinsics.height}; refusing to report a biased coordinate."
            )
        try:
            raw = np.frombuffer(depth_frame.get_data(), dtype=np.uint16).reshape(
                depth_frame.get_height(), depth_frame.get_width()
            )
        except ValueError:
            return None
        # Orbbec V2 depth_scale produces millimetres; convert once to SI metres.
        depth_m = raw.astype(np.float32) * float(depth_frame.get_depth_scale()) / 1000.0
        depth_m[raw == 0] = np.nan
        if depth_m.shape != bgr.shape[:2]:
            raise RuntimeError(
                f"D2C alignment size mismatch: color={bgr.shape[:2]}, depth={depth_m.shape}. "
                "Update SDK/firmware or try a compatible stream profile."
            )
        return bgr, depth_m

    def calibration_dict(self) -> dict:
        if self.camera_param is None:
            raise RuntimeError("Camera is not started")
        p = self.camera_param

        def intrinsics(value):
            return {
                "width": int(value.width), "height": int(value.height),
                "fx": float(value.fx), "fy": float(value.fy),
                "cx": float(value.cx), "cy": float(value.cy),
            }

        def distortion(value):
            return {key: float(getattr(value, key)) for key in ("k1", "k2", "k3", "p1", "p2")}

        ext = p.transform
        return {
            "source": "Orbbec SDK factory calibration for active stream profiles",
            "coordinate_convention": {
                "frame": "color_camera_optical_frame",
                "origin": "RGB optical center",
                "axes": {"x": "right", "y": "down", "z": "forward"},
                "length_unit": "metre (runtime); extrinsic translation below is millimetre",
            },
            "device": self.device_info,
            "rgb_intrinsics": intrinsics(p.rgb_intrinsic),
            "depth_intrinsics": intrinsics(p.depth_intrinsic),
            "rgb_distortion": distortion(p.rgb_distortion),
            "depth_distortion": distortion(p.depth_distortion),
            "depth_to_rgb_extrinsic": {
                "rotation_row_major_3x3": np.asarray(ext.rot, dtype=float).reshape(3, 3).tolist(),
                "translation_mm": np.asarray(ext.transform, dtype=float).tolist(),
            },
            "active_rgb_intrinsics_used": asdict(self.intrinsics),
        }

    def stop(self):
        if self.pipeline is not None:
            try:
                self.pipeline.stop()
            finally:
                self.pipeline = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
