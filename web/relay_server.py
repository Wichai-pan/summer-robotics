#!/usr/bin/env python3
"""Lightweight ForestBridge web relay and dashboard server.

The relay stores structured requests and robot events.  It never imports robot
drivers and cannot issue wheel, servo, ROS, or shell commands.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


FINAL_STATES = {"complete", "failed", "needs_assistance", "stopped", "expired"}
ACTIVE_STATES = {"queued", "assigned", "running"}
DEFAULT_TASK_TTL_S = 15 * 60
MAX_EVENTS_PER_TASK = 500
MAX_MONITOR_FRAME_BYTES = 2 * 1024 * 1024
MONITOR_STATUSES = {"disabled", "waiting", "capturing", "live", "paused", "error"}
MONITOR_SOURCES = {"auto", "gemini", "wrist_white", "wrist_black"}
FRAME_SOURCES = {"gemini", "wrist_white", "wrist_black"}
FRAME_OWNERS = {"monitor", "task"}
TASK_FRAME_LEASE_S = 5
ALLOWED_TASK_TYPES = {"navigate_then_pick_place"}
TASK_PRESETS = {
    "table_pick_place_01": {
        "task_type": "navigate_then_pick_place",
        "goal_x_m": 0.052,
        "goal_y_m": -0.357,
        "goal_yaw_deg": -90.0,
        "act_steps": 600,
    }
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActiveTaskConflict(RuntimeError):
    """Raised when a second active task would be created."""


class RelayStore:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.lock = threading.RLock()
        self.state: dict[str, object] = {
            "tasks": {},
            "robots": {},
            "monitor": {
                "enabled": False,
                "source": "gemini",
                "status": "disabled",
                "message": "监看模式未开启",
                "updated_at": utc_now(),
                "frame": None,
                "task_frame_until": None,
            },
        }
        self.frame_path = state_path.with_name("monitor.jpg")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        if state_path.exists():
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.state["tasks"] = dict(loaded.get("tasks", {}))
                self.state["robots"] = dict(loaded.get("robots", {}))
                monitor = loaded.get("monitor")
                if isinstance(monitor, dict):
                    self.state["monitor"] = monitor

    def _save(self) -> None:
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def _expire_tasks(self) -> None:
        now = datetime.now(timezone.utc)
        for task in self.state["tasks"].values():
            if task.get("status") not in ACTIVE_STATES:
                continue
            expires_at = task.get("expires_at")
            if not isinstance(expires_at, str):
                continue
            try:
                deadline = datetime.fromisoformat(expires_at)
            except ValueError:
                continue
            if deadline <= now:
                task["status"] = "expired"
                task["current_state"] = "expired"
                task["updated_at"] = utc_now()
                task["stop_requested"] = True

    def create_task(
        self,
        request: dict[str, object],
        idempotency_key: str = "",
        ttl_s: int = DEFAULT_TASK_TTL_S,
    ) -> tuple[dict[str, object], bool]:
        task_type = str(request.get("task_type", ""))
        if task_type not in ALLOWED_TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(ALLOWED_TASK_TYPES)}")
        preset_name = str(request.get("preset", "table_pick_place_01"))
        if preset_name not in TASK_PRESETS:
            raise ValueError(f"preset must be one of {sorted(TASK_PRESETS)}")
        preset = TASK_PRESETS[preset_name]
        if task_type != preset["task_type"]:
            raise ValueError("task_type does not match preset")
        forbidden = {"goal_x_m", "goal_y_m", "goal_yaw_deg", "act_steps"}.intersection(request)
        if forbidden:
            raise ValueError("motion parameters are server-defined by the selected preset")
        if not 30 <= ttl_s <= 3600:
            raise ValueError("task TTL must be between 30 and 3600 seconds")
        idempotency_key = idempotency_key.strip()[:128]
        task_id = uuid.uuid4().hex
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        spec = {
            "task_id": task_id,
            "preset": preset_name,
            **preset,
        }
        task: dict[str, object] = {
            "task_id": task_id,
            "status": "queued",
            "current_state": "queued",
            "created_at": now,
            "updated_at": now,
            "expires_at": (now_dt + timedelta(seconds=ttl_s)).isoformat(),
            "idempotency_key": idempotency_key or None,
            "assigned_robot_id": None,
            "stop_requested": False,
            "request_text": str(request.get("request_text", ""))[:500],
            "spec": spec,
            "events": [],
        }
        with self.lock:
            self._expire_tasks()
            if idempotency_key:
                for existing in self.state["tasks"].values():
                    if existing.get("idempotency_key") == idempotency_key:
                        return json.loads(json.dumps(existing)), False
            active = [
                existing
                for existing in self.state["tasks"].values()
                if existing.get("status") in ACTIVE_STATES
            ]
            if active:
                raise ActiveTaskConflict(str(active[0]["task_id"]))
            self.state["tasks"][task_id] = task
            self._save()
        return task, True

    def get_task(self, task_id: str) -> dict[str, object] | None:
        with self.lock:
            self._expire_tasks()
            self._save()
            task = self.state["tasks"].get(task_id)
            return json.loads(json.dumps(task)) if task is not None else None

    def claim_next(self, robot_id: str) -> dict[str, object] | None:
        with self.lock:
            self._expire_tasks()
            queued = [
                task
                for task in self.state["tasks"].values()
                if task.get("status") == "queued" and not task.get("stop_requested")
            ]
            if not queued:
                return None
            task = min(queued, key=lambda item: str(item["created_at"]))
            task["status"] = "assigned"
            task["current_state"] = "assigned"
            task["assigned_robot_id"] = robot_id
            task["updated_at"] = utc_now()
            self._save()
            return json.loads(json.dumps(task))

    def append_event(self, task_id: str, event: dict[str, object]) -> dict[str, object]:
        with self.lock:
            task = self.state["tasks"].get(task_id)
            if task is None:
                raise KeyError(task_id)
            if event.get("task_id") != task_id:
                raise ValueError("event task_id does not match URL")
            events = task["events"]
            assert isinstance(events, list)
            events.append(event)
            if len(events) > MAX_EVENTS_PER_TASK:
                del events[:-MAX_EVENTS_PER_TASK]
            task["current_state"] = str(event.get("state", "unknown"))
            task["updated_at"] = utc_now()
            if event.get("event") == "task_started":
                task["status"] = "running"
            if task["current_state"] in FINAL_STATES:
                task["status"] = task["current_state"]
            self._save()
            return json.loads(json.dumps(task))

    def request_stop(self, task_id: str) -> dict[str, object]:
        with self.lock:
            task = self.state["tasks"].get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task["status"] in FINAL_STATES:
                return json.loads(json.dumps(task))
            task["stop_requested"] = True
            task["updated_at"] = utc_now()
            if task["status"] == "queued":
                task["status"] = "stopped"
                task["current_state"] = "stopped"
            self._save()
            return json.loads(json.dumps(task))

    def heartbeat(self, robot_id: str, body: dict[str, object]) -> dict[str, object]:
        with self.lock:
            robot = {
                "robot_id": robot_id,
                "last_seen": utc_now(),
                "status": str(body.get("status", "online")),
                "current_task_id": body.get("current_task_id"),
            }
            self.state["robots"][robot_id] = robot
            self._save()
            return json.loads(json.dumps(robot))

    def _task_active(self) -> bool:
        tasks = self.state["tasks"]
        assert isinstance(tasks, dict)
        return any(task.get("status") in ACTIVE_STATES for task in tasks.values())

    def monitor_summary(self) -> dict[str, object]:
        with self.lock:
            monitor = self.state["monitor"]
            assert isinstance(monitor, dict)
            result = json.loads(json.dumps(monitor))
            result["task_active"] = self._task_active()
            task_frame_until = monitor.get("task_frame_until")
            task_frame_active = False
            if isinstance(task_frame_until, str):
                try:
                    task_frame_active = datetime.fromisoformat(task_frame_until) > datetime.now(
                        timezone.utc
                    )
                except ValueError:
                    pass
            result["task_frame_active"] = task_frame_active
            return result

    def set_monitor_enabled(self, enabled: bool, source: str = "gemini") -> dict[str, object]:
        if source not in MONITOR_SOURCES:
            raise ValueError(f"monitor source must be one of {sorted(MONITOR_SOURCES)}")
        with self.lock:
            monitor = self.state["monitor"]
            assert isinstance(monitor, dict)
            monitor.update(
                {
                    "enabled": enabled,
                    "source": source,
                    "status": "waiting" if enabled else "disabled",
                    "message": "等待 Jetson 相机画面" if enabled else "监看模式未开启",
                    "updated_at": utc_now(),
                    "frame": None,
                    "task_frame_until": None,
                }
            )
            if not enabled:
                self.frame_path.unlink(missing_ok=True)
            self._save()
            return self.monitor_summary()

    def update_monitor_status(self, status: str, message: str) -> dict[str, object]:
        if status not in MONITOR_STATUSES:
            raise ValueError(f"monitor status must be one of {sorted(MONITOR_STATUSES)}")
        with self.lock:
            monitor = self.state["monitor"]
            assert isinstance(monitor, dict)
            if not monitor.get("enabled") and status != "disabled":
                return self.monitor_summary()
            monitor["status"] = status
            monitor["message"] = message[:240]
            monitor["updated_at"] = utc_now()
            self._save()
            return self.monitor_summary()

    def update_monitor_frame(
        self, data: bytes, source: str = "gemini", owner: str = "monitor"
    ) -> dict[str, object]:
        if not data or len(data) > MAX_MONITOR_FRAME_BYTES:
            raise ValueError("monitor frame must be a non-empty JPEG no larger than 2 MiB")
        if not data.startswith(b"\xff\xd8"):
            raise ValueError("monitor frame is not a JPEG")
        if source not in FRAME_SOURCES:
            raise ValueError(f"frame source must be one of {sorted(FRAME_SOURCES)}")
        if owner not in FRAME_OWNERS:
            raise ValueError(f"frame owner must be one of {sorted(FRAME_OWNERS)}")
        with self.lock:
            monitor = self.state["monitor"]
            assert isinstance(monitor, dict)
            if not monitor.get("enabled"):
                raise ValueError("monitor mode is disabled")
            selected_source = str(monitor.get("source", "auto"))
            if selected_source != "auto" and source != selected_source:
                raise ValueError(
                    f"frame source {source} does not match selected source {selected_source}"
                )
            temporary = self.frame_path.with_name(f".{self.frame_path.name}.tmp")
            temporary.write_bytes(data)
            os.replace(temporary, self.frame_path)
            now = utc_now()
            source_labels = {
                "gemini": "Gemini",
                "wrist_white": "白臂手部摄像头",
                "wrist_black": "黑臂手部摄像头",
            }
            label = source_labels.get(source, "机器人摄像头")
            task_frame_until = (
                (datetime.now(timezone.utc) + timedelta(seconds=TASK_FRAME_LEASE_S)).isoformat()
                if owner == "task"
                else None
            )
            monitor.update(
                {
                    "status": "live",
                    "message": (
                        f"{label}任务画面已连接"
                        if owner == "task"
                        else f"{label}低频画面已连接"
                    ),
                    "updated_at": now,
                    "frame": {
                        "updated_at": now,
                        "bytes": len(data),
                        "source": source,
                        "owner": owner,
                    },
                    "task_frame_until": task_frame_until,
                }
            )
            self._save()
            return self.monitor_summary()

    def summary(self) -> dict[str, object]:
        with self.lock:
            self._expire_tasks()
            self._save()
            tasks = sorted(
                self.state["tasks"].values(),
                key=lambda task: str(task["created_at"]),
                reverse=True,
            )
            return json.loads(json.dumps({
                "tasks": tasks[:20],
                "robots": self.state["robots"],
                "monitor": self.monitor_summary(),
            }))


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "ForestBridgeRelay/0.1"

    @property
    def app(self) -> "RelayHTTPServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} - {format_string % args}")

    def _authorized(self, role: str) -> bool:
        expected = self.app.ui_token if role == "ui" else self.app.robot_token
        if not self.app.ui_token and not self.app.robot_token:
            return True
        return bool(expected) and self.headers.get("Authorization") == f"Bearer {expected}"

    def _authorized_any(self) -> bool:
        return self._authorized("ui") or self._authorized("robot")

    def _json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return body

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "text/javascript",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_types.get(path.suffix, 'application/octet-stream')}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_monitor_frame(self) -> None:
        path = self.app.store.frame_path
        monitor = self.app.store.monitor_summary()
        if not monitor.get("enabled") or not path.exists():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "monitor frame unavailable"})
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok", "time": utc_now()})
            return
        if path == "/api/state":
            if not self._authorized("ui"):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "UI authorization required"})
                return
            self._send_json(HTTPStatus.OK, self.app.store.summary())
            return
        if path == "/api/monitor":
            if not self._authorized_any():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "authorization required"})
                return
            self._send_json(HTTPStatus.OK, self.app.store.monitor_summary())
            return
        if path == "/api/monitor/frame":
            if not self._authorized("ui"):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "UI authorization required"})
                return
            self._send_monitor_frame()
            return
        if path.startswith("/api/tasks/"):
            if not self._authorized_any():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "authorization required"})
                return
            task_id = path[len("/api/tasks/") :].strip("/")
            task = self.app.store.get_task(task_id)
            self._send_json(HTTPStatus.OK if task else HTTPStatus.NOT_FOUND, task or {"error": "task not found"})
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (self.app.static_root / relative).resolve()
        if self.app.static_root.resolve() not in candidate.parents and candidate != self.app.static_root.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self._send_file(candidate)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/monitor/frame":
                if not self._authorized("robot"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "robot authorization required"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_MONITOR_FRAME_BYTES:
                    raise ValueError("monitor frame must be between 1 byte and 2 MiB")
                if self.headers.get("Content-Type", "").split(";", 1)[0] != "image/jpeg":
                    raise ValueError("monitor frame Content-Type must be image/jpeg")
                source = self.headers.get("X-ForestBridge-Camera-Source", "gemini")
                owner = self.headers.get("X-ForestBridge-Frame-Owner", "monitor")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.store.update_monitor_frame(
                        self.rfile.read(length), source=source, owner=owner
                    ),
                )
                return
            body = self._json_body()
            if path == "/api/monitor/control":
                if not self._authorized("ui"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "UI authorization required"})
                    return
                enabled = body.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be a boolean")
                source = str(body.get("source", self.app.store.monitor_summary().get("source", "gemini")))
                self._send_json(HTTPStatus.OK, self.app.store.set_monitor_enabled(enabled, source))
                return
            if path == "/api/monitor/status":
                if not self._authorized("robot"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "robot authorization required"})
                    return
                self._send_json(
                    HTTPStatus.OK,
                    self.app.store.update_monitor_status(
                        str(body.get("status", "error")), str(body.get("message", ""))
                    ),
                )
                return
            if path == "/api/tasks":
                if not self._authorized("ui"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "UI authorization required"})
                    return
                task, created = self.app.store.create_task(
                    body,
                    idempotency_key=self.headers.get("Idempotency-Key", ""),
                    ttl_s=self.app.task_ttl_s,
                )
                self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK, task)
                return
            if path.startswith("/api/robots/") and path.endswith("/claim"):
                if not self._authorized("robot"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "robot authorization required"})
                    return
                robot_id = path[len("/api/robots/") : -len("/claim")].strip("/")
                task = self.app.store.claim_next(robot_id)
                self._send_json(HTTPStatus.OK, {"task": task})
                return
            if path.startswith("/api/robots/") and path.endswith("/heartbeat"):
                if not self._authorized("robot"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "robot authorization required"})
                    return
                robot_id = path[len("/api/robots/") : -len("/heartbeat")].strip("/")
                self._send_json(HTTPStatus.OK, self.app.store.heartbeat(robot_id, body))
                return
            if path.startswith("/api/tasks/") and path.endswith("/events"):
                if not self._authorized("robot"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "robot authorization required"})
                    return
                task_id = path[len("/api/tasks/") : -len("/events")].strip("/")
                self._send_json(HTTPStatus.OK, self.app.store.append_event(task_id, body))
                return
            if path.startswith("/api/tasks/") and path.endswith("/stop"):
                if not self._authorized("ui"):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "UI authorization required"})
                    return
                task_id = path[len("/api/tasks/") : -len("/stop")].strip("/")
                self._send_json(HTTPStatus.OK, self.app.store.request_stop(task_id))
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "endpoint not found"})
        except KeyError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "task not found"})
        except ActiveTaskConflict as exc:
            self._send_json(
                HTTPStatus.CONFLICT,
                {"error": "another task is already active", "active_task_id": str(exc)},
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


class RelayHTTPServer(ThreadingHTTPServer):
    def __init__(self, address, handler, store, static_root, ui_token, robot_token, task_ttl_s):
        super().__init__(address, handler)
        self.store = store
        self.static_root = static_root
        self.ui_token = ui_token
        self.robot_token = robot_token
        self.task_ttl_s = task_ttl_s


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state", type=Path, default=Path("/tmp/forestbridge-relay/state.json"))
    parser.add_argument("--static-root", type=Path, default=Path(__file__).parent / "static")
    parser.add_argument("--task-ttl-s", type=int, default=DEFAULT_TASK_TTL_S)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = RelayHTTPServer(
        (args.host, args.port),
        RelayHandler,
        RelayStore(args.state),
        args.static_root,
        os.environ.get("FORESTBRIDGE_UI_TOKEN", ""),
        os.environ.get("FORESTBRIDGE_ROBOT_TOKEN", ""),
        args.task_ttl_s,
    )
    print(f"ForestBridge relay listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
