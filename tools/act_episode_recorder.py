#!/usr/bin/env python3
"""LeRobot ACT episode writer and headless RGB camera adapters.

This module contains no motor commands.  The leader/follower controller calls
``ACTEpisodeRecorder.add_control_frame`` only after it has read the follower
state and sent the corresponding command.  The recorder owns one Gemini RGB
stream and the white-arm wrist camera and writes successful episodes to a
local LeRobotDataset.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
STATE_NAMES = tuple(f"{joint}.pos" for joint in JOINT_NAMES)
ACTION_NAMES = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    # The deployed wrap-safe controller really sends velocity to motor 5.
    # Recording it as a position would silently change the action semantics.
    "wrist_roll.vel_deg_s",
    "gripper.pos",
)
CAMERA_NAMES = ("gemini_rgb", "white_wrist_rgb")


def feature_specs_match(actual: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    """Compare metadata loaded from JSON (list shapes) with runtime specs."""
    if actual is None:
        return False
    return (
        actual.get("dtype") == expected.get("dtype")
        and tuple(actual.get("shape", ())) == tuple(expected.get("shape", ()))
        and actual.get("names") == expected.get("names")
    )


class CameraStreamError(RuntimeError):
    """A required camera is missing, stale, or has changed format."""


@dataclass(frozen=True)
class CameraSample:
    rgb: np.ndarray
    monotonic_s: float
    sequence: int


class LatestRGBSource:
    """Background RGB source with freshness and duplicate-frame accounting."""

    def __init__(self, name: str, width: int, height: int, fps: int) -> None:
        self.name = name
        self.width = width
        self.height = height
        self.fps = fps
        self.identity: dict[str, Any] = {"name": name}
        self._lock = threading.Lock()
        self._latest: CameraSample | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    def start(self, warmup_timeout_s: float = 8.0) -> None:
        self._open()
        self._thread = threading.Thread(target=self._run_guarded, name=f"{self.name}-rgb", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + warmup_timeout_s
        while time.monotonic() < deadline:
            if self._error is not None:
                raise CameraStreamError(f"{self.name} capture failed: {self._error}") from self._error
            with self._lock:
                if self._latest is not None:
                    return
            time.sleep(0.02)
        raise CameraStreamError(f"{self.name} produced no RGB frame within {warmup_timeout_s:.1f}s")

    def _run_guarded(self) -> None:
        try:
            self._capture_loop()
        except BaseException as exc:  # propagate a background failure to the control loop
            self._error = exc

    def _publish(self, rgb: np.ndarray, timestamp: float, sequence: int) -> None:
        if rgb.dtype != np.uint8 or rgb.shape != (self.height, self.width, 3):
            raise CameraStreamError(
                f"{self.name} frame changed format: {rgb.shape}/{rgb.dtype}; "
                f"expected {(self.height, self.width, 3)}/uint8"
            )
        with self._lock:
            self._latest = CameraSample(rgb=np.ascontiguousarray(rgb), monotonic_s=timestamp, sequence=sequence)

    def latest(self, max_age_s: float) -> CameraSample:
        if self._error is not None:
            raise CameraStreamError(f"{self.name} capture failed: {self._error}") from self._error
        with self._lock:
            sample = self._latest
        if sample is None:
            raise CameraStreamError(f"{self.name} has no RGB frame")
        age = time.monotonic() - sample.monotonic_s
        if age > max_age_s:
            raise CameraStreamError(f"{self.name} frame is stale: age={age:.3f}s > {max_age_s:.3f}s")
        return sample

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._close()

    def _open(self) -> None:
        raise NotImplementedError

    def _capture_loop(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError


class OpenCVRGBSource(LatestRGBSource):
    def __init__(self, device: str, width: int, height: int, fps: int) -> None:
        super().__init__("white_wrist_rgb", width, height, fps)
        self.device = device
        self.capture: cv2.VideoCapture | None = None

    def _open(self) -> None:
        cv2.setNumThreads(1)
        capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        if not capture.isOpened():
            capture.release()
            raise CameraStreamError(f"cannot open white wrist camera {self.device}")
        actual = (
            int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))),
            int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))),
        )
        if actual != (self.width, self.height):
            capture.release()
            raise CameraStreamError(
                f"white wrist camera returned {actual[0]}x{actual[1]}, expected {self.width}x{self.height}"
            )
        self.capture = capture
        self.identity = {
            "name": self.name,
            "device": self.device,
            "transport": "V4L2/MJPG",
            "width": self.width,
            "height": self.height,
            "requested_fps": self.fps,
            "reported_fps": float(capture.get(cv2.CAP_PROP_FPS)),
        }

    def _capture_loop(self) -> None:
        assert self.capture is not None
        sequence = 0
        while not self._stop.is_set():
            ok, bgr = self.capture.read()
            captured = time.monotonic()
            if not ok or bgr is None:
                raise CameraStreamError("white wrist V4L2 read failed")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            self._publish(rgb, captured, sequence)
            sequence += 1

    def _close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None


class GeminiRGBSource(LatestRGBSource):
    def __init__(self, width: int, height: int, fps: int) -> None:
        super().__init__("gemini_rgb", width, height, fps)
        self.ob: Any = None
        self.pipeline: Any = None
        self.started = False

    @staticmethod
    def _member(obj: Any, names: tuple[str, ...]) -> str | None:
        for name in names:
            try:
                value = getattr(obj, name)
                return str(value() if callable(value) else value)
            except Exception:
                pass
        return None

    def _open(self) -> None:
        try:
            import pyorbbecsdk as ob
        except ImportError as exc:
            raise CameraStreamError("pyorbbecsdk2 is not installed") from exc
        self.ob = ob
        context = ob.Context()
        devices = context.query_devices()
        if devices.get_count() != 1:
            raise CameraStreamError(f"expected exactly one Gemini, found {devices.get_count()}")
        pipeline = ob.Pipeline()
        config = ob.Config()
        profiles = pipeline.get_stream_profile_list(ob.OBSensorType.COLOR_SENSOR)
        profile = None
        errors: list[str] = []
        for fmt in (ob.OBFormat.MJPG, ob.OBFormat.RGB):
            try:
                profile = profiles.get_video_stream_profile(self.width, self.height, fmt, self.fps)
                break
            except Exception as exc:
                errors.append(f"{fmt}: {exc}")
        if profile is None:
            raise CameraStreamError(
                f"Gemini has no {self.width}x{self.height}@{self.fps} MJPG/RGB profile: {'; '.join(errors)}"
            )
        config.enable_stream(profile)
        pipeline.start(config)
        self.pipeline = pipeline
        self.started = True
        try:
            info = pipeline.get_device().get_device_info()
            self.identity = {
                "name": self.name,
                "device_name": self._member(info, ("get_name", "name")),
                "serial_number": self._member(info, ("get_serial_number", "serial_number")),
                "firmware_version": self._member(info, ("get_firmware_version", "firmware_version")),
                "connection_type": self._member(info, ("get_connection_type", "connection_type")),
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
            }
        except Exception:
            self.identity = {"name": self.name, "width": self.width, "height": self.height, "fps": self.fps}

    def _decode(self, frame: Any) -> np.ndarray:
        ob = self.ob
        data = np.frombuffer(frame.get_data(), dtype=np.uint8)
        height, width = frame.get_height(), frame.get_width()
        fmt = frame.get_format()
        if fmt == ob.OBFormat.MJPG:
            bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if bgr is None:
                raise CameraStreamError("Gemini MJPG decode failed")
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if fmt == ob.OBFormat.RGB:
            return data.reshape((height, width, 3)).copy()
        raise CameraStreamError(f"unsupported Gemini RGB format {fmt}")

    def _capture_loop(self) -> None:
        sequence = 0
        while not self._stop.is_set():
            frames = self.pipeline.wait_for_frames(500)
            if frames is None:
                continue
            frame = frames.get_color_frame()
            if frame is None:
                continue
            self._publish(self._decode(frame), time.monotonic(), sequence)
            sequence += 1

    def _close(self) -> None:
        if self.started and self.pipeline is not None:
            self.pipeline.stop()
        self.started = False
        self.pipeline = None


def dataset_features(width: int, height: int) -> dict[str, dict[str, Any]]:
    return {
        "observation.state": {"dtype": "float32", "shape": (6,), "names": list(STATE_NAMES)},
        "action": {"dtype": "float32", "shape": (6,), "names": list(ACTION_NAMES)},
        "observation.images.gemini_rgb": {
            "dtype": "video",
            "shape": (height, width, 3),
            "names": ["height", "width", "channels"],
        },
        "observation.images.white_wrist_rgb": {
            "dtype": "video",
            "shape": (height, width, 3),
            "names": ["height", "width", "channels"],
        },
        "diagnostic.black_leader_state": {
            "dtype": "float32",
            "shape": (6,),
            "names": list(STATE_NAMES),
        },
        "diagnostic.white_tracking_error": {
            "dtype": "float32",
            "shape": (6,),
            "names": list(STATE_NAMES),
        },
        "diagnostic.camera_age_s": {
            "dtype": "float32",
            "shape": (2,),
            "names": list(CAMERA_NAMES),
        },
        "diagnostic.camera_sequence": {
            "dtype": "int64",
            "shape": (2,),
            "names": list(CAMERA_NAMES),
        },
        "diagnostic.control_elapsed_s": {
            "dtype": "float32",
            "shape": (1,),
            "names": ["elapsed_s"],
        },
    }


def build_control_frame(
    *,
    task: str,
    white_state: dict[str, float],
    action: dict[str, float],
    black_state: dict[str, float],
    tracking_error: dict[str, float],
    gemini: CameraSample,
    wrist: CameraSample,
    control_elapsed_s: float,
    now_s: float | None = None,
) -> dict[str, Any]:
    now = time.monotonic() if now_s is None else now_s
    return {
        "observation.state": np.asarray([white_state[name] for name in JOINT_NAMES], dtype=np.float32),
        "action": np.asarray([action[name] for name in JOINT_NAMES], dtype=np.float32),
        "observation.images.gemini_rgb": gemini.rgb,
        "observation.images.white_wrist_rgb": wrist.rgb,
        "diagnostic.black_leader_state": np.asarray(
            [black_state[name] for name in JOINT_NAMES], dtype=np.float32
        ),
        "diagnostic.white_tracking_error": np.asarray(
            [tracking_error[name] for name in JOINT_NAMES], dtype=np.float32
        ),
        "diagnostic.camera_age_s": np.asarray(
            [now - gemini.monotonic_s, now - wrist.monotonic_s], dtype=np.float32
        ),
        "diagnostic.camera_sequence": np.asarray([gemini.sequence, wrist.sequence], dtype=np.int64),
        "diagnostic.control_elapsed_s": np.asarray([control_elapsed_s], dtype=np.float32),
        "task": task,
    }


class ACTEpisodeRecorder:
    """One-successful-episode-at-a-time LeRobotDataset recorder."""

    def __init__(
        self,
        *,
        root: Path,
        repo_id: str,
        task: str,
        scene_version: str,
        fps: int,
        width: int,
        height: int,
        camera_fps: int,
        white_wrist_device: str,
        max_camera_age_s: float = 0.25,
        max_duplicate_control_frames: int = 2,
    ) -> None:
        self.root = root
        self.repo_id = repo_id
        self.task = task
        self.scene_version = scene_version
        self.fps = fps
        self.width = width
        self.height = height
        self.max_camera_age_s = max_camera_age_s
        self.max_duplicate_control_frames = max_duplicate_control_frames
        self.gemini = GeminiRGBSource(width, height, camera_fps)
        self.wrist = OpenCVRGBSource(white_wrist_device, width, height, camera_fps)
        self.dataset: Any = None
        self.frame_count = 0
        self._last_sequences: tuple[int, int] | None = None
        self._duplicate_counts = [0, 0]
        self._closed = False

    def start(self) -> None:
        try:
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
        except ImportError as exc:
            raise RuntimeError(
                "LeRobot dataset dependencies are missing; rebuild the Jetson image from deploy/jetson/Dockerfile"
            ) from exc
        try:
            self.gemini.start()
            self.wrist.start()
            features = dataset_features(self.width, self.height)
            info_path = self.root / "meta" / "info.json"
            if info_path.exists():
                dataset = LeRobotDataset.resume(
                    repo_id=self.repo_id,
                    root=self.root,
                    video_backend="pyav",
                    image_writer_threads=4,
                )
                if not all(
                    feature_specs_match(dataset.features.get(key), expected)
                    for key, expected in features.items()
                ):
                    dataset.finalize()
                    raise RuntimeError("existing dataset schema differs; create a new dataset version/root")
                if dataset.fps != self.fps:
                    dataset.finalize()
                    raise RuntimeError(f"existing dataset fps={dataset.fps}, requested fps={self.fps}")
                self.dataset = dataset
            else:
                if self.root.exists() and any(self.root.iterdir()):
                    raise RuntimeError(f"dataset root exists but is not a resumable LeRobotDataset: {self.root}")
                self.dataset = LeRobotDataset.create(
                    repo_id=self.repo_id,
                    root=self.root,
                    fps=self.fps,
                    features=features,
                    robot_type="xlerobot_white_arm_black_leader",
                    use_videos=True,
                    video_backend="pyav",
                    image_writer_threads=4,
                )
            self._write_manifest()
        except Exception:
            self.gemini.close()
            self.wrist.close()
            raise

    def _write_manifest(self) -> None:
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            commit = None
        payload = {
            "schema": "forestbridge_fixed_pick_place_act/v1",
            "repo_id": self.repo_id,
            "scene_version": self.scene_version,
            "task": self.task,
            "fps": self.fps,
            "image_shape": [self.height, self.width, 3],
            "state_names": list(STATE_NAMES),
            "action_names": list(ACTION_NAMES),
            "action_semantics": {
                "position_joints": "actual normalized Goal_Position sent after slew/bounds",
                "wrist_roll": "actual wrap-safe Goal_Velocity converted to degrees/second",
            },
            "cameras": [self.gemini.identity, self.wrist.identity],
            "git_commit": commit,
            "created_unix_s": time.time(),
        }
        path = self.root / "forestbridge" / "session_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def add_control_frame(
        self,
        *,
        white_state: dict[str, float],
        action: dict[str, float],
        black_state: dict[str, float],
        tracking_error: dict[str, float],
        control_elapsed_s: float,
    ) -> None:
        if self.dataset is None:
            raise RuntimeError("recorder is not started")
        gemini = self.gemini.latest(self.max_camera_age_s)
        wrist = self.wrist.latest(self.max_camera_age_s)
        sequences = (gemini.sequence, wrist.sequence)
        if self._last_sequences is not None:
            for index, sequence in enumerate(sequences):
                if sequence == self._last_sequences[index]:
                    self._duplicate_counts[index] += 1
                else:
                    self._duplicate_counts[index] = 0
        self._last_sequences = sequences
        stale = [
            CAMERA_NAMES[index]
            for index, count in enumerate(self._duplicate_counts)
            if count > self.max_duplicate_control_frames
        ]
        if stale:
            raise CameraStreamError(
                f"camera frames repeated too many control cycles: {stale}, sequences={sequences}"
            )
        frame = build_control_frame(
            task=self.task,
            white_state=white_state,
            action=action,
            black_state=black_state,
            tracking_error=tracking_error,
            gemini=gemini,
            wrist=wrist,
            control_elapsed_s=control_elapsed_s,
        )
        self.dataset.add_frame(frame)
        self.frame_count += 1

    def finish(self, success: bool, failure_reason: str | None = None) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("recorder is already closed")
        if self.dataset is None:
            raise RuntimeError("recorder is not started")
        before = int(self.dataset.num_episodes)
        if success:
            if self.frame_count < max(2, self.fps):
                raise RuntimeError(
                    f"episode has only {self.frame_count} frames; refusing to save a sub-second episode"
                )
            self.dataset.save_episode()
        else:
            self.dataset.clear_episode_buffer()
        self.dataset.finalize()
        self.gemini.close()
        self.wrist.close()
        self._closed = True
        result = {
            "scene_version": self.scene_version,
            "task": self.task,
            "success": bool(success),
            "failure_reason": failure_reason,
            "captured_frames": self.frame_count,
            "saved_episode_index": before if success else None,
            "dataset_root": str(self.root),
            "unix_s": time.time(),
        }
        if success:
            try:
                self._verify_reopen(expected_episodes=before + 1)
            except Exception as exc:
                result["success"] = False
                result["failure_reason"] = f"finalize_reopen_verification_failed: {exc}"
                self._append_ledger(result)
                raise RuntimeError(
                    "episode was encoded but failed reopen verification; quarantine this dataset root"
                ) from exc
        self._append_ledger(result)
        return result

    def _append_ledger(self, result: dict[str, Any]) -> None:
        ledger = self.root.parent / "session_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    def abort(self, reason: str) -> None:
        if self._closed:
            return
        try:
            if self.dataset is not None:
                self.dataset.clear_episode_buffer()
                self.dataset.finalize()
        finally:
            self.gemini.close()
            self.wrist.close()
            self._closed = True
        self._append_ledger(
            {
                "scene_version": self.scene_version,
                "task": self.task,
                "success": False,
                "failure_reason": reason,
                "captured_frames": self.frame_count,
                "dataset_root": str(self.root),
                "unix_s": time.time(),
            }
        )

    def _verify_reopen(self, expected_episodes: int) -> None:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        reopened = LeRobotDataset(
            repo_id=self.repo_id,
            root=self.root,
            video_backend="pyav",
            download_videos=False,
        )
        if reopened.num_episodes != expected_episodes:
            raise RuntimeError(
                f"finalized dataset reopened with {reopened.num_episodes} episodes; "
                f"expected {expected_episodes}"
            )
        if reopened.num_frames < self.frame_count:
            raise RuntimeError(
                f"finalized dataset reopened with only {reopened.num_frames} total frames"
            )
