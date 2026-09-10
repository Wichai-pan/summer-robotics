#!/usr/bin/env python3
"""Upload opt-in, low-rate Gemini snapshots to the ForestBridge relay.

This process never opens a serial port or commands a motor. The camera remains
closed while monitoring is disabled or while a relay task is active.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from forestbridge_shared_rgb import SharedRGBError, SharedRGBReader


class RelayClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict[str, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": content_type},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("relay response must be a JSON object")
        return payload

    def monitor(self) -> dict[str, object]:
        return self._request("GET", "/api/monitor")

    def status(self, status: str, message: str) -> None:
        self._request(
            "POST",
            "/api/monitor/status",
            json.dumps({"status": status, "message": message}).encode("utf-8"),
        )

    def upload(self, frame: bytes, source: str) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/monitor/frame",
            data=frame,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "image/jpeg",
                "X-ForestBridge-Camera-Source": source,
                "X-ForestBridge-Frame-Owner": "monitor",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("relay response must be a JSON object")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="https://robot.wichai.xyz")
    parser.add_argument("--token", default=os.environ.get("FORESTBRIDGE_ROBOT_TOKEN", ""))
    parser.add_argument(
        "--repo-root", type=Path, default=Path("/home/jetsonl7/summer-robotics-deploy")
    )
    parser.add_argument(
        "--frame",
        type=Path,
        default=Path("/home/jetsonl7/robot-data/runtime/forestbridge-monitor.jpg"),
    )
    parser.add_argument("--interval-s", type=float, default=2.0)
    parser.add_argument("--poll-s", type=float, default=1.0)
    parser.add_argument(
        "--gemini-shared-frame-dir",
        type=Path,
        default=Path("/dev/shm/forestbridge-gemini"),
    )
    parser.add_argument("--gemini-shared-max-age-s", type=float, default=1.0)
    parser.add_argument(
        "--task-active-dir",
        type=Path,
        default=Path("/home/jetsonl7/robot-data/runtime/forestbridge-task-active"),
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def foreground_task_active(task_dir: Path) -> bool:
    """Return true for a live/recent guard and clean up a proven stale guard."""
    if not task_dir.is_dir():
        return False
    owner = task_dir / "owner"
    try:
        lines = owner.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0])
        expected_start = lines[1]
        actual_start = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
        if actual_start == expected_start:
            return True
    except (OSError, ValueError, IndexError):
        # mkdir precedes the owner write by a few microseconds. Treat a new,
        # incomplete guard as live rather than racing it for the camera.
        try:
            if time.time() - task_dir.stat().st_mtime < 30:
                return True
        except OSError:
            return False
    shutil.rmtree(task_dir, ignore_errors=True)
    return False


def run_snapshot_interruptibly(
    command: list[str], *, cwd: Path, task_active_dir: Path, timeout_s: float = 20.0
) -> subprocess.CompletedProcess[str]:
    """Run an idle snapshot while allowing a foreground task to preempt it."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_s
    interrupted = False
    timed_out = False
    while process.poll() is None:
        if foreground_task_active(task_active_dir):
            interrupted = True
            os.killpg(process.pid, signal.SIGTERM)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            break
        time.sleep(0.1)
    try:
        stdout, stderr = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    if interrupted:
        return subprocess.CompletedProcess(command, 3, stdout, stderr)
    if timed_out:
        return subprocess.CompletedProcess(command, 124, stdout, stderr)
    return subprocess.CompletedProcess(command, int(process.returncode or 0), stdout, stderr)


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("missing --token or FORESTBRIDGE_ROBOT_TOKEN")
    if args.interval_s < 1.0 or args.poll_s < 0.25:
        raise SystemExit("monitor interval must be >=1.0s and poll interval >=0.25s")
    if args.gemini_shared_max_age_s <= 0:
        raise SystemExit("shared Gemini frame age must be positive")
    args.frame.parent.mkdir(parents=True, exist_ok=True)
    client = RelayClient(args.relay, args.token)
    gemini_reader = SharedRGBReader(args.gemini_shared_frame_dir)
    last_report = ""
    while True:
        try:
            foreground = foreground_task_active(args.task_active_dir)
            monitor = client.monitor()
            if not monitor.get("enabled"):
                last_report = ""
                if args.once:
                    return 0
                time.sleep(args.poll_s)
                continue
            if monitor.get("task_frame_active"):
                # A manually launched local task may not have a relay task ID.
                # Its recent frame lease still prevents this process from
                # opening a competing camera handle or overwriting task status.
                last_report = "task"
                time.sleep(args.poll_s)
                continue

            source = str(monitor.get("source", "gemini"))
            if source == "auto":
                source = "gemini"
            if source == "gemini":
                frame = gemini_reader.latest_jpeg(args.gemini_shared_max_age_s)
                client.upload(frame.jpeg, source)
                last_report = "live"
                if args.once:
                    return 0
                time.sleep(args.interval_s)
                continue
            elif source in {"wrist_white", "wrist_black"}:
                if foreground or monitor.get("task_active"):
                    if last_report != "paused":
                        client.status("paused", "机器人任务正在使用所选手部摄像头")
                        last_report = "paused"
                    if args.once:
                        return 0
                    time.sleep(args.poll_s)
                    continue
                white = source == "wrist_white"
                label = "白臂手部" if white else "黑臂手部"
                device_args = ["--wrist-a" if white else "--wrist-b"]
                device = "/dev/wrist-2-4-1" if white else "/dev/wrist-2-4-3"
                snapshot_args = [
                    "python3", "/data/services/forestbridge-monitor/uvc_rgb_snapshot.py",
                    "--device", device, "--jpeg-quality", "70",
                    "--output", "/data/runtime/forestbridge-monitor.jpg",
                ]
            else:
                client.status("error", f"未知摄像头来源：{source}")
                time.sleep(args.poll_s)
                continue
            client.status("capturing", f"正在读取{label}低频快照")
            command = [
                "bash", str(args.repo_root / "scripts" / "jetson_robot_exec.sh"),
                *device_args, "--", *snapshot_args,
            ]
            completed = run_snapshot_interruptibly(
                command,
                cwd=args.repo_root,
                task_active_dir=args.task_active_dir,
            )
            if completed.returncode == 3:
                client.status("paused", "Gemini 正被本地机器人流程占用，监看已暂停")
                last_report = "paused"
            elif completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "snapshot failed").strip()
                message = detail.splitlines()[-1] if detail else "snapshot failed"
                client.status("error", f"Gemini 快照失败：{message}"[:240])
                last_report = "error"
            else:
                client.upload(args.frame.read_bytes(), source)
                last_report = "live"
            if args.once:
                return 0 if last_report == "live" else 1
            time.sleep(args.interval_s)
        except (
            OSError,
            RuntimeError,
            SharedRGBError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
            urllib.error.URLError,
            ValueError,
        ) as exc:
            print(f"camera monitor error: {exc}", flush=True)
            if args.once:
                return 1
            time.sleep(max(args.poll_s, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
