from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "web" / "relay_server.py"
SPEC = importlib.util.spec_from_file_location("forestbridge_relay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_store_create_claim_event_stop_and_reload(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = MODULE.RelayStore(state_path)
    task, created = store.create_task({"task_type": "navigate_then_pick_place", "request_text": "test"})
    assert created is True

    claimed = store.claim_next("jetson-dry-run")
    assert claimed is not None
    assert claimed["task_id"] == task["task_id"]
    assert store.claim_next("other-robot") is None

    event = {
        "task_id": task["task_id"],
        "state": "localizing",
        "event": "state_started",
        "timestamp": "2026-08-27T00:00:00+00:00",
    }
    updated = store.append_event(task["task_id"], event)
    assert updated["current_state"] == "localizing"
    stopped = store.request_stop(task["task_id"])
    assert stopped["stop_requested"] is True

    reloaded = MODULE.RelayStore(state_path).get_task(task["task_id"])
    assert reloaded is not None
    assert reloaded["events"] == [event]
    assert reloaded["stop_requested"] is True


def test_store_rejects_arbitrary_task_and_out_of_range_act_steps(tmp_path: Path) -> None:
    store = MODULE.RelayStore(tmp_path / "state.json")

    try:
        store.create_task({"task_type": "run_shell"})
    except ValueError as exc:
        assert "task_type" in str(exc)
    else:
        raise AssertionError("arbitrary task type was accepted")

    try:
        store.create_task({"task_type": "navigate_then_pick_place", "act_steps": 9000})
    except ValueError as exc:
        assert "server-defined" in str(exc)
    else:
        raise AssertionError("unsafe ACT step count was accepted")


def test_heartbeat_is_persisted_for_offline_detection(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = MODULE.RelayStore(state_path)
    heartbeat = store.heartbeat("jetson-dry-run", {"status": "idle", "current_task_id": None})

    assert heartbeat["status"] == "idle"
    summary = json.loads(state_path.read_text(encoding="utf-8"))
    assert summary["robots"]["jetson-dry-run"]["last_seen"]


def test_stop_after_terminal_state_does_not_relabel_completed_task(tmp_path: Path) -> None:
    store = MODULE.RelayStore(tmp_path / "state.json")
    task, _ = store.create_task({"task_type": "navigate_then_pick_place"})
    store.claim_next("jetson-dry-run")
    store.append_event(
        task["task_id"],
        {
            "task_id": task["task_id"],
            "state": "complete",
            "event": "task_completed",
            "timestamp": "2026-08-27T00:00:00+00:00",
        },
    )

    unchanged = store.request_stop(task["task_id"])

    assert unchanged["status"] == "complete"
    assert unchanged["stop_requested"] is False


def test_single_active_task_idempotency_and_expiry(tmp_path: Path) -> None:
    store = MODULE.RelayStore(tmp_path / "state.json")
    first, created = store.create_task(
        {"task_type": "navigate_then_pick_place"},
        idempotency_key="same-click",
    )
    duplicate, duplicate_created = store.create_task(
        {"task_type": "navigate_then_pick_place"},
        idempotency_key="same-click",
    )
    assert created is True
    assert duplicate_created is False
    assert duplicate["task_id"] == first["task_id"]

    try:
        store.create_task(
            {"task_type": "navigate_then_pick_place"},
            idempotency_key="new-click",
        )
    except MODULE.ActiveTaskConflict as exc:
        assert str(exc) == first["task_id"]
    else:
        raise AssertionError("second active task was accepted")

    store.state["tasks"][first["task_id"]]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    replacement, replacement_created = store.create_task(
        {"task_type": "navigate_then_pick_place"},
        idempotency_key="new-click",
    )
    assert replacement_created is True
    assert replacement["task_id"] != first["task_id"]
    assert store.get_task(first["task_id"])["status"] == "expired"


def test_http_role_tokens_are_separated(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text("ok", encoding="utf-8")
    server = MODULE.RelayHTTPServer(
        ("127.0.0.1", 0),
        MODULE.RelayHandler,
        MODULE.RelayStore(tmp_path / "state.json"),
        static_root,
        "ui-secret",
        "robot-secret",
        900,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(path: str, token: str, method: str = "GET", body: bytes | None = None):
        return urllib.request.urlopen(
            urllib.request.Request(
                base + path,
                data=body,
                method=method,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            ),
            timeout=2,
        )

    try:
        with request("/api/state", "ui-secret") as response:
            assert response.status == 200
        try:
            request("/api/state", "robot-secret")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("robot token was accepted for UI state")
        with request(
            "/api/robots/test/heartbeat",
            "robot-secret",
            method="POST",
            body=b"{}",
        ) as response:
            assert response.status == 200
        try:
            request(
                "/api/robots/test/heartbeat",
                "ui-secret",
                method="POST",
                body=b"{}",
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("UI token was accepted for robot heartbeat")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_monitor_is_opt_in_and_frame_is_removed_when_disabled(tmp_path: Path) -> None:
    store = MODULE.RelayStore(tmp_path / "state.json")
    assert store.monitor_summary()["enabled"] is False

    enabled = store.set_monitor_enabled(True, "wrist_white")
    assert enabled["status"] == "waiting"
    assert enabled["source"] == "wrist_white"
    assert enabled["task_active"] is False

    jpeg = b"\xff\xd8" + b"forestbridge" + b"\xff\xd9"
    live = store.update_monitor_frame(jpeg, source="wrist_white", owner="task")
    assert live["status"] == "live"
    assert live["task_frame_active"] is True
    assert live["frame"]["source"] == "wrist_white"
    assert live["frame"]["owner"] == "task"
    assert "任务画面" in live["message"]
    assert store.frame_path.read_bytes() == jpeg

    disabled = store.set_monitor_enabled(False)
    assert disabled["status"] == "disabled"
    assert disabled["frame"] is None
    assert not store.frame_path.exists()


def test_monitor_rejects_frame_while_disabled_and_invalid_status(tmp_path: Path) -> None:
    store = MODULE.RelayStore(tmp_path / "state.json")
    try:
        store.update_monitor_frame(b"\xff\xd8bad\xff\xd9")
    except ValueError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("frame was accepted while monitor mode was disabled")

    try:
        store.update_monitor_status("moving", "invalid")
    except ValueError as exc:
        assert "monitor status" in str(exc)
    else:
        raise AssertionError("invalid monitor status was accepted")


def test_monitor_auto_accepts_task_sources_and_fixed_source_rejects_mismatch(
    tmp_path: Path,
) -> None:
    store = MODULE.RelayStore(tmp_path / "state.json")
    jpeg = b"\xff\xd8task-frame\xff\xd9"
    store.set_monitor_enabled(True, "auto")
    auto = store.update_monitor_frame(jpeg, source="gemini", owner="task")
    assert auto["frame"]["source"] == "gemini"

    store.set_monitor_enabled(True, "wrist_black")
    try:
        store.update_monitor_frame(jpeg, source="gemini", owner="task")
    except ValueError as exc:
        assert "does not match selected source" in str(exc)
    else:
        raise AssertionError("fixed camera selection accepted a mismatched task frame")
