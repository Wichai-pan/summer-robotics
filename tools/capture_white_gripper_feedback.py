#!/usr/bin/env python3
"""Capture one labelled white-gripper feedback trial.

The script keeps arm joints 1-5 torque-free, moves only the gripper, and
records the STS3215 goal, position, velocity, load and current registers.
It deliberately keeps these signals outside the ACT observation vector: this
first dataset is for deriving and validating a deterministic grasp supervisor.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


GRIPPER = "gripper"
LABEL_TARGETS = {
    "open": 5.0,
    "empty_close": 60.0,
    "grasp": 60.0,
    "slip": 60.0,
}
LABEL_INSTRUCTIONS = {
    "open": "两指之间保持完全清空；夹爪应处于张开状态。",
    "empty_close": "两指之间不要放任何物体；本次测量空夹闭合。",
    "grasp": "把面霜居中放在两指之间；本次测量正确夹持。",
    "slip": "把面霜浅放或略微偏置，但不要故意卡死舵机；本次测量夹偏/滑落。",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=tuple(LABEL_TARGETS), required=True)
    parser.add_argument("--white-port")
    parser.add_argument("--white-id", default="white_arm_leader_follow")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/data/act/gripper_feedback_v1"),
    )
    parser.add_argument(
        "--target",
        type=float,
        help="override the labelled normalized gripper target (commissioning only)",
    )
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--speed-per-s", type=float, default=20.0)
    parser.add_argument("--hold-s", type=float, default=2.0)
    parser.add_argument(
        "--max-close-target",
        type=float,
        default=60.0,
        help="hard upper bound for this feedback experiment",
    )
    parser.add_argument(
        "--max-temperature-c",
        type=float,
        default=65.0,
        help="abort before this temperature is exceeded",
    )
    parser.add_argument("--note", default="")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def converted_feedback(velocity_raw: int, load_raw: int, current_raw: int) -> dict[str, float]:
    """Return readable estimates while preserving raw registers as authority."""
    return {
        # The configured STS3215 velocity-unit factor can change the physical
        # scale. Do not use this nominal value for a safety decision.
        "velocity_nominal_deg_s": float(velocity_raw) * 360.0 / 4096.0,
        "load_abs_percent": abs(float(load_raw)) / 10.0,
        "current_estimated_ma": float(current_raw) * 6.5,
    }


def slew_value(current: float, target: float, maximum_step: float) -> float:
    return current + max(-maximum_step, min(maximum_step, target - current))


def metric_summary(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("cannot summarize an empty metric")
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "maximum": max(values),
    }


def summarize_samples(samples: list[dict]) -> dict[str, object]:
    hold = [sample for sample in samples if sample["phase"] == "hold"]
    selected = hold or samples
    return {
        "sample_count": len(samples),
        "hold_sample_count": len(hold),
        "hold_or_all": {
            field: metric_summary([float(sample[field]) for sample in selected])
            for field in (
                "position_error_normalized",
                "present_velocity_raw",
                "present_load_raw",
                "present_load_abs_percent",
                "present_current_raw",
                "present_current_estimated_ma",
            )
        },
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite feedback trial: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def normalized_from_raw(bus: object, motor: str, raw: int) -> float:
    motor_id = bus.motors[motor].id
    return float(bus._normalize({motor_id: int(raw)})[motor_id])


def read_feedback(bus: object, commanded: float, elapsed_s: float, phase: str) -> dict:
    goal_raw = int(bus.read("Goal_Position", GRIPPER, normalize=False, num_retry=2))
    position_raw = int(bus.read("Present_Position", GRIPPER, normalize=False, num_retry=2))
    velocity_raw = int(bus.read("Present_Velocity", GRIPPER, normalize=False, num_retry=2))
    load_raw = int(bus.read("Present_Load", GRIPPER, normalize=False, num_retry=2))
    current_raw = int(bus.read("Present_Current", GRIPPER, normalize=False, num_retry=2))
    temperature_c = int(bus.read("Present_Temperature", GRIPPER, normalize=False, num_retry=2))
    status_raw = int(bus.read("Status", GRIPPER, normalize=False, num_retry=2))
    present_normalized = normalized_from_raw(bus, GRIPPER, position_raw)
    converted = converted_feedback(velocity_raw, load_raw, current_raw)
    return {
        "elapsed_s": elapsed_s,
        "phase": phase,
        "commanded_position_normalized": commanded,
        "goal_position_raw": goal_raw,
        "goal_position_normalized": normalized_from_raw(bus, GRIPPER, goal_raw),
        "present_position_raw": position_raw,
        "present_position_normalized": present_normalized,
        "position_error_normalized": commanded - present_normalized,
        "present_velocity_raw": velocity_raw,
        "present_load_raw": load_raw,
        "present_current_raw": current_raw,
        "present_temperature_c": temperature_c,
        "status_raw": status_raw,
        "present_velocity_nominal_deg_s": converted["velocity_nominal_deg_s"],
        "present_load_abs_percent": converted["load_abs_percent"],
        "present_current_estimated_ma": converted["current_estimated_ma"],
    }


def main() -> int:
    args = parse_args()
    target = LABEL_TARGETS[args.label] if args.target is None else args.target
    positive = (
        args.fps,
        args.speed_per_s,
        args.hold_s,
        args.max_close_target,
        args.max_temperature_c,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("rates, durations and limits must be positive finite values")
    if not math.isfinite(target) or not 0.0 <= target <= args.max_close_target:
        raise SystemExit(
            f"target must be in [0, {args.max_close_target:.1f}], got {target}"
        )
    if args.execute and not sys.stdin.isatty():
        raise SystemExit("interactive TTY required for --execute")

    from portutil import BOARDS, PortResolutionError, resolve_port

    try:
        port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    from lerobot.motors.feetech import OperatingMode
    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    robot = SO100Follower(
        SO100FollowerConfig(
            port=port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )
    connected = False
    torque_enable_attempted = False
    samples: list[dict] = []
    started_at = datetime.now(timezone.utc)
    output_path = args.output_dir / (
        f"{started_at.strftime('%Y%m%dT%H%M%S_%fZ')}_{args.label}.json"
    )

    try:
        print(f"白臂夹爪反馈采集：{port}；只改变 ID 6 夹爪目标。")
        if args.execute:
            print("程序随后会松开白臂全部扭矩；请先让机械臂稳固落在支撑面上或用手托住。")
            if input(
                "确认机械臂已被支撑、夹爪空间清空且可立即切断12V；输入 PREPARED："
            ).strip() != "PREPARED":
                print("已取消；尚未打开串口或改变任何电机状态。")
                return 0
        robot.bus.connect()
        connected = True
        if args.execute:
            robot.bus.disable_torque()
        if not robot.is_calibrated:
            raise RuntimeError(
                f"white motor registers do not match calibration {args.white_id}"
            )

        initial_raw = int(
            robot.bus.read("Present_Position", GRIPPER, normalize=False, num_retry=2)
        )
        initial_position = normalized_from_raw(robot.bus, GRIPPER, initial_raw)
        initial_feedback = {
            "position_raw": initial_raw,
            "position_normalized": initial_position,
            "temperature_c": int(
                robot.bus.read(
                    "Present_Temperature", GRIPPER, normalize=False, num_retry=2
                )
            ),
            "status_raw": int(
                robot.bus.read("Status", GRIPPER, normalize=False, num_retry=2)
            ),
        }
        if initial_feedback["temperature_c"] >= args.max_temperature_c:
            raise RuntimeError(
                f"gripper is already {initial_feedback['temperature_c']}°C; "
                "leave motor power off and let it cool"
            )
        if initial_feedback["status_raw"] != 0:
            raise RuntimeError(
                f"gripper status register is nonzero ({initial_feedback['status_raw']}); "
                "resolve the motor alarm before sampling"
            )
        print(
            f"标签={args.label}；当前夹爪={initial_position:.2f}；"
            f"目标={target:.2f}；最高只到 {args.max_close_target:.1f}。"
        )
        print(LABEL_INSTRUCTIONS[args.label])
        print("执行期间其他五个关节保持松扭矩，不会收到任何位置目标。")
        if not args.execute:
            print("DRY RUN：未启用扭矩或发送位置目标。添加 --execute 才采集。")
            return 0
        if input(
            "确认物体布置与标签一致；输入 SAMPLE 开始："
        ).strip() != "SAMPLE":
            print("已取消；没有启用扭矩或发送动作。")
            return 0

        # The whole arm is already torque-free. Only ID 6 receives a position
        # target and torque; no target is written to IDs 1-5.
        robot.bus.write(
            "Operating_Mode",
            GRIPPER,
            OperatingMode.POSITION.value,
            num_retry=2,
        )
        controller_registers = {
            "P_Coefficient": 16,
            "I_Coefficient": 0,
            "D_Coefficient": 32,
        }
        for register, value in controller_registers.items():
            robot.bus.write(register, GRIPPER, value, normalize=False, num_retry=2)
            readback = int(
                robot.bus.read(register, GRIPPER, normalize=False, num_retry=2)
            )
            if readback != value:
                raise RuntimeError(
                    f"gripper {register} mismatch: wrote {value}, read {readback}"
                )
        calibration = robot.calibration[GRIPPER]
        if not calibration.range_min <= initial_raw <= calibration.range_max:
            raise RuntimeError(
                f"gripper raw position {initial_raw} is outside calibrated range "
                f"[{calibration.range_min}, {calibration.range_max}]; reposition it "
                "manually while torque is off before sampling"
            )
        seeded_raw = initial_raw
        robot.bus.write(
            "Goal_Position", GRIPPER, seeded_raw, normalize=False, num_retry=2
        )
        seeded_readback = int(
            robot.bus.read("Goal_Position", GRIPPER, normalize=False, num_retry=2)
        )
        if seeded_readback != seeded_raw:
            raise RuntimeError(
                f"gripper raw goal seed mismatch: wrote {seeded_raw}, "
                f"read {seeded_readback}"
            )
        # Mark this before the call: Torque_Enable can succeed even if the
        # subsequent Lock write fails inside enable_torque().
        torque_enable_attempted = True
        robot.bus.enable_torque([GRIPPER], num_retry=2)

        period = 1.0 / args.fps
        command = initial_position
        started = time.monotonic()
        previous_loop = started
        hold_started: float | None = None
        maximum_duration = (
            abs(target - initial_position) / args.speed_per_s * 3.0
            + args.hold_s
            + 5.0
        )
        last_print = -1.0
        while True:
            loop_started = time.monotonic()
            elapsed = loop_started - started
            if elapsed > maximum_duration:
                raise RuntimeError(
                    f"feedback trial exceeded {maximum_duration:.1f}s timeout"
                )
            actual_dt = max(0.0, loop_started - previous_loop)
            previous_loop = loop_started
            # Cap a late-loop command increment so a serial stall cannot make
            # the next position target jump.
            command_dt = min(actual_dt, 2.0 * period)
            command = slew_value(command, target, args.speed_per_s * command_dt)
            reached_command = abs(command - target) <= 1e-6
            if reached_command and hold_started is None:
                hold_started = loop_started
            phase = "hold" if hold_started is not None else "motion"
            robot.bus.write("Goal_Position", GRIPPER, command, num_retry=2)
            sample = read_feedback(robot.bus, command, elapsed, phase)
            samples.append(sample)
            if sample["present_temperature_c"] >= args.max_temperature_c:
                raise RuntimeError(
                    f"gripper temperature reached {sample['present_temperature_c']}°C"
                )
            if sample["status_raw"] != 0:
                raise RuntimeError(
                    f"gripper status register became nonzero ({sample['status_raw']})"
                )
            if elapsed - last_print >= 0.5:
                print(
                    "\r"
                    f"{elapsed:4.1f}s {phase:6s} "
                    f"pos={sample['present_position_normalized']:5.1f} "
                    f"err={sample['position_error_normalized']:+5.1f} "
                    f"vel={sample['present_velocity_raw']:+5d} "
                    f"load={sample['present_load_raw']:+5d} "
                    f"current={sample['present_current_raw']:4d}",
                    end="",
                    flush=True,
                )
                last_print = elapsed
            if hold_started is not None and loop_started - hold_started >= args.hold_s:
                break
            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)

        final_raw = int(
            robot.bus.read("Present_Position", GRIPPER, normalize=False, num_retry=2)
        )
        robot.bus.write("Goal_Position", GRIPPER, final_raw, normalize=False, num_retry=2)
        print()
        payload = {
            "schema": "forestbridge_white_gripper_feedback/v1",
            "label": args.label,
            "operator_note": args.note,
            "started_at_utc": started_at.isoformat(),
            "port": port,
            "board_serial": BOARDS["white"],
            "robot_id": args.white_id,
            "motor": {"name": GRIPPER, "id": robot.bus.motors[GRIPPER].id},
            "hardware_policy": {
                "other_joints": "torque-free; no position target sent",
                "gripper": "only motor receiving a position target and torque",
                "controller_registers": controller_registers,
                "torque_limits_changed": False,
                "target_normalized": target,
                "speed_per_s": args.speed_per_s,
                "hold_s": args.hold_s,
            },
            "units": {
                "load": "signed controller output; abs(raw)/10 is percent, not force",
                "current": "raw is authoritative; estimated mA uses 6.5 mA/raw",
                "velocity": (
                    "signed raw is authoritative; nominal deg/s excludes the "
                    "configurable STS velocity-unit factor"
                ),
            },
            "initial_feedback": initial_feedback,
            "summary": summarize_samples(samples),
            "samples": samples,
        }
        atomic_write_json(output_path, payload)
        print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
        print(f"已保存：{output_path}")
        return 0
    finally:
        if connected:
            cleanup_errors: list[str] = []
            try:
                if torque_enable_attempted:
                    # Write Torque_Enable first and separately. Even if the
                    # Lock write or the original enable call failed, ID 6 is
                    # still given an explicit best-effort torque-off command.
                    try:
                        robot.bus.write(
                            "Torque_Enable", GRIPPER, 0, normalize=False, num_retry=5
                        )
                    except Exception as exc:  # pragma: no cover - hardware failure
                        cleanup_errors.append(f"Torque_Enable=0 failed: {exc}")
                    try:
                        robot.bus.write("Lock", GRIPPER, 0, normalize=False, num_retry=3)
                    except Exception as exc:  # pragma: no cover - hardware failure
                        cleanup_errors.append(f"Lock=0 failed: {exc}")
            finally:
                robot.bus.disconnect(disable_torque=False)
            print("采集结束；夹爪和白臂全部处于松扭矩状态。")
            if cleanup_errors:
                print(
                    "警告：夹爪清理命令未全部确认，请立即切断12V："
                    + " | ".join(cleanup_errors),
                    file=sys.stderr,
                )
                if sys.exc_info()[0] is None:
                    raise RuntimeError("gripper torque-off cleanup was not confirmed")


if __name__ == "__main__":
    raise SystemExit(main())
