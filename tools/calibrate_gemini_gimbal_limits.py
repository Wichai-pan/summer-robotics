#!/usr/bin/env python3
"""Release Gemini gimbal torque and record four manually chosen endpoints.

This tool never commands motion and never changes operating mode. It only
sets Torque_Enable=0 on black-board IDs 7/8, then reads the encoders when the
operator presses Enter at left, right, up and down endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from gemini_gimbal_pose import (
    BOARDS,
    DEG_PER_TICK,
    MOTOR_IDS,
    TORQUE_ENABLE,
    connect_black_board,
    inspect_axes,
    load_reference,
    print_axes,
    wrapped_tick_delta,
    write_u8,
)

DEFAULT_REFERENCE = Path("/data/config/gemini_gimbal_grasp_pose_v1.json")
DEFAULT_OUTPUT = Path("/data/config/gemini_gimbal_manual_limits_v1.json")
CAPTURES = (
    ("yaw_left", 7, "把 Gemini 缓慢转到最左侧安全位置"),
    ("yaw_right", 7, "把 Gemini 缓慢转到最右侧安全位置"),
    ("pitch_up", 8, "把 Gemini 缓慢抬到最上侧安全位置"),
    ("pitch_down", 8, "把 Gemini 缓慢压到最下侧安全位置"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="override black-board serial device")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("需要交互式终端")
    reference = load_reference(args.reference)
    reference_raw = {
        motor_id: int(reference["raw_position"][str(motor_id)])
        for motor_id in MOTOR_IDS
    }
    if args.output.exists():
        answer = input(f"{args.output} 已存在；输入 OVERWRITE 才覆盖：").strip()
        if answer != "OVERWRITE":
            raise SystemExit("已取消，原记录未改变")

    device, port, packet = connect_black_board(args.port)
    torque_released = False
    try:
        print_axes(device, inspect_axes(packet, port))
        print("\n程序不会让云台自动运动，只会松开 ID 7/8 扭矩并读取角度。")
        print("请扶住相机；所谓极限应是线缆和结构仍然安全的位置，不要用力顶机械硬限位。")
        if input("输入 RECORD 开始：").strip() != "RECORD":
            print("已取消；没有更改扭矩或记录文件。")
            return 0

        torque_released = True
        for motor_id in MOTOR_IDS:
            write_u8(packet, port, motor_id, TORQUE_ENABLE, 0, "Torque_Enable")
        axes = inspect_axes(packet, port)
        if any(axes[motor_id]["torque_enabled"] for motor_id in MOTOR_IDS):
            raise RuntimeError("ID 7/8 未能全部松扭矩")
        print("ID 7/8 已松扭矩，现在可以用手缓慢移动云台。")

        endpoints: dict[str, dict] = {}
        for index, (name, motor_id, instruction) in enumerate(CAPTURES, start=1):
            answer = input(f"\n[{index}/4] {instruction}；稳定后按 Enter（q 取消）：")
            if answer.strip().lower() == "q":
                raise SystemExit("已取消；没有保存不完整记录")
            current = inspect_axes(packet, port)
            raw = current[motor_id]["raw"]
            delta_deg = wrapped_tick_delta(raw, reference_raw[motor_id]) * DEG_PER_TICK
            endpoints[name] = {
                "motor_id": motor_id,
                "raw": raw,
                "one_turn_deg": raw * DEG_PER_TICK,
                "relative_to_grasp_deg": delta_deg,
                "both_axes_raw": {
                    str(axis_id): current[axis_id]["raw"] for axis_id in MOTOR_IDS
                },
            }
            print(f"已记录 {name}: ID {motor_id} raw={raw}, 相对抓取位={delta_deg:+.2f}°")

        payload = {
            "schema": "forestbridge/gemini_gimbal_manual_limits/v1",
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "board_serial": BOARDS["black"],
            "reference_raw": {str(key): value for key, value in reference_raw.items()},
            "axis_map": reference.get("axis_map", {}),
            "endpoints": endpoints,
            "note": "manually observed endpoints; no motor limit register was written",
        }
        write_json(args.output, payload)
        print(f"\n四个位置已保存：{args.output}")
        print("云台仍处于松扭矩和最后一个手动位置；请运行 return --execute 回到抓取视角。")
        return 0
    finally:
        if torque_released:
            for motor_id in MOTOR_IDS:
                try:
                    write_u8(packet, port, motor_id, TORQUE_ENABLE, 0, "Torque_Enable")
                except Exception as exc:
                    print(f"警告：ID {motor_id} 松扭矩复核失败：{exc}", file=sys.stderr)
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
