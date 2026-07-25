#!/usr/bin/env python3
"""Locally close the base forward loop using a persistent Gemini depth stream.

This is deliberately independent of the LLM: after one explicit operator
authorization, the controller sends low-speed forward commands only while a
fresh centre-ROI depth stream remains above ``--stop-m``. Any bad/stale depth,
serial error, timeout, Ctrl-C, or threshold crossing sends zero wheel velocity
and disables base torque in ``finally``.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler

from base_keyboard import WHEEL_IDS, body_to_wheel_raw, encode_sm
from portutil import BOARDS, PortResolutionError, resolve_port


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPTH_PYTHON = Path.home() / "miniconda3" / "envs" / "orbbec-depth" / "bin" / "python"
OP_MODE, TORQUE, GOAL_VEL, LOCK = 33, 40, 46, 55
MODE_VELOCITY = 1


def stream_reader(stream, samples: queue.Queue[dict[str, object]]) -> None:
    """Read SDK NDJSON while silently skipping its non-JSON startup diagnostics."""
    for line in iter(stream.readline, ""):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and "roi_p10_m" in item:
            while True:
                try:
                    samples.put_nowait(item)
                    break
                except queue.Full:
                    try:
                        samples.get_nowait()
                    except queue.Empty:
                        break


def newest_sample(samples: queue.Queue[dict[str, object]], timeout_s: float) -> dict[str, object] | None:
    try:
        sample = samples.get(timeout=timeout_s)
    except queue.Empty:
        return None
    while True:
        try:
            sample = samples.get_nowait()
        except queue.Empty:
            return sample


def start_depth_stream(args: argparse.Namespace) -> tuple[subprocess.Popen[str], queue.Queue[dict[str, object]]]:
    depth_python = Path(args.depth_python).expanduser()
    if not depth_python.is_file():
        raise SystemExit(f"找不到 Orbbec Python：{depth_python}")
    command = [str(depth_python), str(REPO_ROOT / "tools" / "orbbec_depth_stream.py"), "--max-hz", str(args.depth_hz)]
    if args.depth_sudo:
        command = ["sudo", "-E", *command]
    print("启动常驻 Gemini 深度流…")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=None, text=True, bufsize=1)
    assert process.stdout is not None
    samples: queue.Queue[dict[str, object]] = queue.Queue(maxsize=3)
    threading.Thread(target=stream_reader, args=(process.stdout, samples), daemon=True).start()
    return process, samples


def stop_depth_stream(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-m", type=float, default=0.50, help="P10 小于等于此值立即停止（默认 0.50 m）")
    parser.add_argument("--speed-mps", type=float, default=0.04, help="接近速度，m/s（默认 0.04）")
    parser.add_argument("--max-duration-s", type=float, default=30.0, help="连续接近最长秒数（默认 30）")
    parser.add_argument("--depth-hz", type=float, default=15.0, help="深度检查发布频率（默认 15 Hz）")
    parser.add_argument("--depth-stale-s", type=float, default=0.75, help="超过此秒数无深度帧即停止（默认 0.75）")
    parser.add_argument("--depth-python", default=str(DEFAULT_DEPTH_PYTHON), help="orbbec-depth 环境的 Python")
    parser.add_argument("--depth-sudo", action="store_true", help="用 sudo -E 启动 Orbbec 深度流（本 Mac 通常需要）")
    parser.add_argument("--dry-run", action="store_true", help="只读取/判断深度，绝不打开底盘串口")
    parser.add_argument("port", nargs="?", help="可选：手动覆盖白板端口")
    args = parser.parse_args()
    if not 0.20 <= args.stop_m <= 3.0 or not 0 < args.speed_mps <= 0.06 or args.max_duration_s <= 0:
        raise SystemExit("--stop-m 必须为 0.20–3.0；--speed-mps 必须为 0–0.06；--max-duration-s 必须为正数。")

    depth_process: subprocess.Popen[str] | None = None
    port_handler = None
    packet = None
    started = 0.0
    commanded = False
    try:
        depth_process, samples = start_depth_stream(args)
        initial = newest_sample(samples, args.depth_stale_s + 4.0)
        if initial is None:
            raise SystemExit("未在启动时间内收到有效 Gemini 深度帧；取消接近。")
        print(
            f"初始深度 P10={float(initial['roi_p10_m']):.3f} m，目标检查点={args.stop_m:.3f} m，"
            f"速度={args.speed_mps:.3f} m/s。"
        )
        if args.dry_run:
            print("DRY RUN：不会打开串口或发送轮速；等待深度到阈值或超时。")
        else:
            answer = input(
                "连续低速接近会在 P10 ≤ 目标值、深度丢失或超时时自动停止。"
                "确认路径清空、双臂收好且可立即断开 12V？输入 APPROACH 执行： "
            ).strip()
            if answer != "APPROACH":
                print("已取消；没有发送底盘指令。")
                return 2
            override = args.port or os.environ.get("XLEROBOT_PORT")
            try:
                port = resolve_port(BOARDS["white"], override=override)
            except PortResolutionError as exc:
                raise SystemExit(str(exc)) from exc
            print(f"白板（底盘）端口：{port}")
            port_handler = PortHandler(port)
            if not port_handler.openPort():
                raise SystemExit("无法打开白板串口。确认 USB 与 12V 供电。")
            port_handler.setBaudRate(1_000_000)
            packet = PacketHandler(0)
            missing = []
            for motor_id in WHEEL_IDS:
                _, comm_result, _ = packet.ping(port_handler, motor_id)
                if comm_result != COMM_SUCCESS:
                    missing.append(motor_id)
            if missing:
                raise SystemExit(f"底盘电机 {missing} 没有响应；取消接近。")
            for motor_id in WHEEL_IDS:
                mode, _, _ = packet.read1ByteTxRx(port_handler, motor_id, OP_MODE)
                if mode != MODE_VELOCITY:
                    packet.write1ByteTxRx(port_handler, motor_id, LOCK, 0)
                    packet.write1ByteTxRx(port_handler, motor_id, OP_MODE, MODE_VELOCITY)
                    packet.write1ByteTxRx(port_handler, motor_id, LOCK, 1)
                packet.write1ByteTxRx(port_handler, motor_id, TORQUE, 1)

        raw = body_to_wheel_raw(x=args.speed_mps, y=0.0, theta=0.0)
        started = time.monotonic()
        last_report = 0.0
        while True:
            elapsed = time.monotonic() - started
            if elapsed > args.max_duration_s:
                print(f"达到 {args.max_duration_s:.1f} s 连续接近上限；停止并请求下一阶段授权。")
                return 0
            sample = newest_sample(samples, args.depth_stale_s)
            if sample is None:
                print(f"超过 {args.depth_stale_s:.2f} s 未收到有效深度；立即停止。")
                return 1
            p10 = float(sample["roi_p10_m"])
            median = float(sample["roi_median_m"])
            if p10 <= args.stop_m:
                print(f"到达接近检查点：P10={p10:.3f} m ≤ {args.stop_m:.3f} m。停止并请求下一阶段授权。")
                return 0
            if not args.dry_run:
                for motor_id, velocity in zip(WHEEL_IDS, raw):
                    packet.write2ByteTxRx(port_handler, motor_id, GOAL_VEL, encode_sm(velocity))
                commanded = True
            if elapsed - last_report >= 0.5:
                action = "would move" if args.dry_run else "moving"
                print(f"{action}: P10={p10:.3f} m, median={median:.3f} m, elapsed={elapsed:.1f} s")
                last_report = elapsed
    except KeyboardInterrupt:
        print("收到 Ctrl-C；立即停止。")
        return 130
    finally:
        if packet is not None and port_handler is not None:
            for motor_id in WHEEL_IDS:
                try:
                    packet.write2ByteTxRx(port_handler, motor_id, GOAL_VEL, 0)
                    packet.write1ByteTxRx(port_handler, motor_id, TORQUE, 0)
                except Exception:
                    pass
            port_handler.closePort()
            if commanded:
                print("底盘已停止并松扭矩，端口已关闭。")
        stop_depth_stream(depth_process)


if __name__ == "__main__":
    raise SystemExit(main())
