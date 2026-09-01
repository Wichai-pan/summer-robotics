#!/usr/bin/env python3
"""Non-blocking, low-rate task-owned camera preview publisher.

Robot task code calls :meth:`offer` with RGB arrays it already owns.  A daemon
thread selects the browser-requested source, JPEG-encodes only the newest frame
and uploads it to the authenticated relay.  It never opens a camera or touches
serial/motor devices, and network failures never interrupt the control loop.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable


VALID_SOURCES = {"gemini", "wrist_white", "wrist_black"}


class TaskFramePublisher:
    def __init__(
        self,
        *,
        relay_url: str | None = None,
        token: str | None = None,
        interval_s: float = 2.0,
        jpeg_quality: int = 70,
        preferred_sources: Iterable[str] = ("gemini",),
    ) -> None:
        self.relay_url = (
            relay_url or os.environ.get("FORESTBRIDGE_RELAY_URL", "")
        ).rstrip("/")
        self.token = token or os.environ.get("FORESTBRIDGE_ROBOT_TOKEN", "")
        self.enabled = bool(
            self.relay_url
            and self.token
            and os.environ.get("FORESTBRIDGE_TASK_PREVIEW", "0") == "1"
        )
        self.interval_s = max(1.0, float(interval_s))
        self.jpeg_quality = max(30, min(90, int(jpeg_quality)))
        self.preferred_sources = tuple(preferred_sources)
        if any(source not in VALID_SOURCES for source in self.preferred_sources):
            raise ValueError("preferred_sources contains an unknown camera")
        self._frames: dict[str, object] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="forestbridge-task-preview", daemon=True
        )
        self._thread.start()

    def offer(self, source: str, rgb_frame: object) -> None:
        """Offer the newest RGB numpy array without blocking the task loop."""
        if not self.enabled or source not in VALID_SOURCES:
            return
        with self._lock:
            # The camera sources reuse buffers on some backends.  Copy here so
            # JPEG encoding cannot race the next camera read.
            self._frames[source] = rgb_frame.copy()  # type: ignore[attr-defined]

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        content_type: str = "application/json",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": content_type,
        }
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            self.relay_url + path,
            data=data,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("relay response must be a JSON object")
        return payload

    def _select_source(self, monitor: dict[str, object]) -> tuple[str, object] | None:
        with self._lock:
            if not self._frames:
                return None
            selected = str(monitor.get("source", "auto"))
            if selected != "auto":
                frame = self._frames.get(selected)
                return (selected, frame) if frame is not None else None
            for source in self.preferred_sources:
                frame = self._frames.get(source)
                if frame is not None:
                    return source, frame
            source, frame = next(iter(self._frames.items()))
            return source, frame

    def _run(self) -> None:
        import cv2

        while not self._stop.is_set():
            try:
                monitor = self._request("GET", "/api/monitor")
                if monitor.get("enabled"):
                    selected = self._select_source(monitor)
                    if selected is not None:
                        source, rgb = selected
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            bgr,
                            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
                        )
                        if ok:
                            self._request(
                                "POST",
                                "/api/monitor/frame",
                                encoded.tobytes(),
                                "image/jpeg",
                                {
                                    "X-ForestBridge-Camera-Source": source,
                                    "X-ForestBridge-Frame-Owner": "task",
                                },
                            )
            except (
                OSError,
                RuntimeError,
                ValueError,
                urllib.error.URLError,
            ) as exc:
                print(f"task preview warning: {exc}", flush=True)
            self._stop.wait(self.interval_s)
