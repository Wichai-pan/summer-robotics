from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
RELAY_PATH = REPO_ROOT / "web" / "relay_server.py"
SPEC = importlib.util.spec_from_file_location("forestbridge_worker_test_relay", RELAY_PATH)
assert SPEC is not None and SPEC.loader is not None
RELAY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RELAY
SPEC.loader.exec_module(RELAY)


def request(base: str, path: str, token: str, method: str = "GET", body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.load(response)


def test_dry_run_worker_completes_authenticated_http_task(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text("ok", encoding="utf-8")
    server = RELAY.RelayHTTPServer(
        ("127.0.0.1", 0),
        RELAY.RelayHandler,
        RELAY.RelayStore(tmp_path / "state.json"),
        static_root,
        "ui-secret",
        "robot-secret",
        900,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        task = request(
            base,
            "/api/tasks",
            "ui-secret",
            method="POST",
            body={
                "task_type": "navigate_then_pick_place",
                "preset": "table_pick_place_01",
                "request_text": "integration test",
            },
        )
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "forestbridge_robot_worker.py"),
                "--relay",
                base,
                "--token",
                "robot-secret",
                "--robot-id",
                "jetson-test",
                "--output-root",
                str(tmp_path / "worker"),
                "--state-delay-s",
                "0",
                "--once",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        finished = request(base, f"/api/tasks/{task['task_id']}", "ui-secret")
        assert finished["status"] == "complete"
        assert len(finished["events"]) == 20
        state = request(base, "/api/state", "ui-secret")
        assert state["robots"]["jetson-test"]["status"] == "idle"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
