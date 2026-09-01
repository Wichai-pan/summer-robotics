#!/usr/bin/env python3
"""Outbound-only dry-run robot worker for the ForestBridge relay."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from forestbridge_task_executive import (  # noqa: E402
    DryRunSkillRunner,
    EventWriter,
    TaskExecutive,
    TaskSpec,
)


class RelayClient:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("relay response must be a JSON object")
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="http://127.0.0.1:8787")
    parser.add_argument("--robot-id", default="jetson-dry-run")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/forestbridge-worker"))
    parser.add_argument("--poll-s", type=float, default=1.0)
    parser.add_argument("--state-delay-s", type=float, default=0.7)
    parser.add_argument("--token", default="")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = RelayClient(args.relay, args.token)
    completed = 0
    while True:
        try:
            client.request(
                "POST",
                f"/api/robots/{args.robot_id}/heartbeat",
                {"status": "idle", "current_task_id": None},
            )
            response = client.request("POST", f"/api/robots/{args.robot_id}/claim", {})
            task = response.get("task")
            if not isinstance(task, dict):
                if args.once:
                    return 0
                time.sleep(args.poll_s)
                continue

            spec_payload = task["spec"]
            assert isinstance(spec_payload, dict)
            task_id = str(task["task_id"])
            spec = TaskSpec(
                task_id=task_id,
                task_type=str(spec_payload["task_type"]),
                goal_x_m=float(spec_payload["goal_x_m"]),
                goal_y_m=float(spec_payload["goal_y_m"]),
                goal_yaw_deg=float(spec_payload["goal_yaw_deg"]),
                act_steps=int(spec_payload["act_steps"]),
            )
            output_dir = args.output_root / task_id

            def publish(event: dict[str, object]) -> None:
                client.request("POST", f"/api/tasks/{task_id}/events", event)
                client.request(
                    "POST",
                    f"/api/robots/{args.robot_id}/heartbeat",
                    {"status": "busy", "current_task_id": task_id},
                )

            def stop_requested() -> bool:
                try:
                    current = client.request("GET", f"/api/tasks/{task_id}")
                except (OSError, urllib.error.URLError):
                    return True
                return bool(current.get("stop_requested"))

            client.request(
                "POST",
                f"/api/robots/{args.robot_id}/heartbeat",
                {"status": "busy", "current_task_id": task_id},
            )
            writer = EventWriter(
                task_id=task_id,
                events_path=output_dir / "events.jsonl",
                status_path=output_dir / "status.json",
                observer=publish,
            )
            executive = TaskExecutive(
                runner=DryRunSkillRunner(delay_s=args.state_delay_s),
                writer=writer,
                stop_requested=stop_requested,
            )
            executive.run(spec)
            client.request(
                "POST",
                f"/api/robots/{args.robot_id}/heartbeat",
                {"status": "idle", "current_task_id": None},
            )
            completed += 1
            if args.once and completed >= 1:
                return 0
        except (OSError, KeyError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            print(f"worker relay error: {exc}", file=sys.stderr, flush=True)
            if args.once:
                return 1
            time.sleep(max(args.poll_s, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
