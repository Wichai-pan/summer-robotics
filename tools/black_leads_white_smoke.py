#!/usr/bin/env python3
"""Supervised black-arm -> white-arm leader/follower test.

The black arm is always torque-free and read only.  The white arm mirrors
relative motion by default.  ``--absolute-follow`` first aligns the white arm
to the black arm's calibrated joint pose, then follows absolute joint targets.
"""

from __future__ import annotations

import argparse
import select
import sys
import termios
import time
import tty

from portutil import BOARDS, PortResolutionError, resolve_port


JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)

# Physical motion is intentionally locked after the 2026-08-09 white wrist
# overload incident.  Do not remove this guard until raw Present_Position and
# Goal_Position round-trip checks, cable clearance, and a torque-free hardware
# diagnostic have all passed on the real robot.
MOTION_LOCKED_REASON = (
    "MOTION LOCKED: white wrist_roll overloaded near the 0/4095 encoder wrap "
    "during initial alignment. Keep 12V motor power off and complete a "
    "torque-free raw-position/goal-register diagnostic before using this script."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded black-arm leader -> white-arm follower test"
    )
    parser.add_argument("--black-port", help="optional black-board port override")
    parser.add_argument("--white-port", help="optional white-board port override")
    parser.add_argument(
        "--black-id",
        default="black_arm",
        help="LeRobot calibration id for the hand-moved black arm",
    )
    parser.add_argument(
        "--white-id",
        default="white_arm_xlerobot",
        help="LeRobot calibration id for the powered white arm",
    )
    parser.add_argument(
        "--install-white-wrist-range",
        action="store_true",
        help=(
            "while torque is off, install only the cached wrist_roll min/max "
            "into the white motor after strict calibration checks"
        ),
    )
    parser.add_argument(
        "--invert",
        nargs="*",
        choices=JOINTS,
        default=[],
        help="joints whose leader-to-follower mapping should be sign-inverted",
    )
    parser.add_argument(
        "--absolute-follow",
        action="store_true",
        help="slowly align the white arm to the black pose, then follow absolute angles",
    )
    parser.add_argument(
        "--align-speed-deg-s",
        type=float,
        default=15.0,
        help="white-arm joint speed limit during the initial alignment",
    )
    parser.add_argument(
        "--align-gripper-speed-s",
        type=float,
        default=30.0,
        help="white gripper speed limit during the initial alignment",
    )
    parser.add_argument(
        "--align-timeout-s",
        type=float,
        default=20.0,
        help="maximum time allowed for the initial alignment",
    )
    parser.add_argument(
        "--align-final-error-deg",
        type=float,
        default=3.0,
        help="required final arm-joint accuracy before alignment is accepted",
    )
    parser.add_argument(
        "--max-align-delta-deg",
        type=float,
        default=120.0,
        help="refuse initial alignment if any non-roll arm joint exceeds this delta",
    )
    parser.add_argument(
        "--max-delta-deg",
        type=float,
        default=5.0,
        help="maximum total white-arm displacement from startup for arm joints",
    )
    parser.add_argument(
        "--max-gripper-delta",
        type=float,
        default=10.0,
        help="maximum total gripper displacement from startup (0-100 units)",
    )
    parser.add_argument(
        "--full-range",
        action="store_true",
        help="remove startup-relative excursion limits; calibrated motor ranges still apply",
    )
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument(
        "--max-speed-deg-s",
        type=float,
        default=30.0,
        help="white-arm joint command slew rate; this is a speed limit, not a range limit",
    )
    parser.add_argument(
        "--max-gripper-speed-s",
        type=float,
        default=60.0,
        help="white gripper command slew rate in 0-100 units per second",
    )
    parser.add_argument(
        "--tracking-error-deg",
        type=float,
        default=12.0,
        help="abort when a commanded arm joint cannot track within this error",
    )
    parser.add_argument(
        "--start-range-tolerance-ticks",
        type=int,
        default=32,
        help=(
            "allow a torque-free startup pose this many raw ticks beyond a calibrated "
            "limit; the initial goal is clamped back to the limit"
        ),
    )
    return parser.parse_args()


def positions(observation: dict[str, object]) -> dict[str, float]:
    result = {
        key.removesuffix(".pos"): float(value)
        for key, value in observation.items()
        if key.endswith(".pos")
    }
    missing = [joint for joint in JOINTS if joint not in result]
    if missing:
        raise RuntimeError(f"missing joint observations: {missing}")
    return result


def bounded_relative_targets(
    black_now: dict[str, float],
    black_start: dict[str, float],
    white_start: dict[str, float],
    signs: dict[str, float],
    max_delta_deg: float,
    max_gripper_delta: float,
    full_range: bool = False,
) -> dict[str, float]:
    targets: dict[str, float] = {}
    for joint in JOINTS:
        limit = max_gripper_delta if joint == "gripper" else max_delta_deg
        relative = signs[joint] * (black_now[joint] - black_start[joint])
        if not full_range:
            relative = max(-limit, min(limit, relative))
        target = white_start[joint] + relative
        if joint == "gripper":
            target = max(0.0, min(100.0, target))
        targets[f"{joint}.pos"] = target
    return targets


def absolute_targets(
    black_now: dict[str, float], signs: dict[str, float]
) -> dict[str, float]:
    """Map calibrated leader angles directly into follower coordinates."""
    targets = {
        f"{joint}.pos": signs[joint] * black_now[joint] for joint in JOINTS
    }
    targets["gripper.pos"] = max(0.0, min(100.0, targets["gripper.pos"]))
    return targets


def wrapped_delta_deg(current: float, previous: float) -> float:
    """Return the signed shortest change between two one-turn angles."""
    return (current - previous + 180.0) % 360.0 - 180.0


def calibrated_target_bounds(robot: object) -> dict[str, tuple[float, float]]:
    """Return commandable normalized bounds implied by the calibration."""
    bounds: dict[str, tuple[float, float]] = {}
    for joint in JOINTS:
        calibration = robot.calibration[joint]
        if joint == "gripper":
            bounds[joint] = (0.0, 100.0)
        else:
            span_deg = (calibration.range_max - calibration.range_min) * 360.0 / 4095.0
            bounds[joint] = (-span_deg / 2.0, span_deg / 2.0)
    return bounds


def clamp_to_bounds(
    action: dict[str, float], bounds: dict[str, tuple[float, float]]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in action.items():
        joint = key.removesuffix(".pos")
        lower, upper = bounds[joint]
        result[key] = max(lower, min(upper, value))
    return result


def target_bound_violations(
    action: dict[str, float], bounds: dict[str, tuple[float, float]]
) -> dict[str, tuple[float, float, float]]:
    violations = {}
    for key, value in action.items():
        joint = key.removesuffix(".pos")
        lower, upper = bounds[joint]
        if value < lower or value > upper:
            violations[joint] = (value, lower, upper)
    return violations


def slew_toward(
    current_command: dict[str, float],
    desired: dict[str, float],
    arm_step: float,
    gripper_step: float,
) -> dict[str, float]:
    command: dict[str, float] = {}
    for key, target in desired.items():
        joint = key.removesuffix(".pos")
        step = gripper_step if joint == "gripper" else arm_step
        previous = current_command[key]
        change = max(-step, min(step, target - previous))
        command[key] = previous + change
    return command


def move_to_alignment(
    robot: object,
    current: dict[str, float],
    target: dict[str, float],
    fps: float,
    arm_speed: float,
    gripper_speed: float,
    tracking_error: float,
    timeout_s: float,
    final_error: float,
) -> dict[str, float]:
    """Move through small normalized joint steps to an already-validated target."""
    period = 1.0 / fps
    arm_step = arm_speed / fps
    gripper_step = gripper_speed / fps
    command = dict(current)
    started = time.monotonic()
    last_print = 0.0

    while True:
        loop_started = time.monotonic()
        if loop_started - started > timeout_s:
            raise RuntimeError(f"initial alignment timed out after {timeout_s:.1f}s")

        command = slew_toward(command, target, arm_step, gripper_step)
        robot.bus.sync_write(
            "Goal_Position",
            {key.removesuffix(".pos"): value for key, value in command.items()},
        )
        measured = positions(robot.get_observation())
        arm_errors = {
            joint: abs(command[f"{joint}.pos"] - measured[joint])
            for joint in JOINTS
            if joint != "gripper"
        }
        worst_joint = max(arm_errors, key=arm_errors.get)
        if arm_errors[worst_joint] > tracking_error:
            raise RuntimeError(
                f"alignment tracking error {arm_errors[worst_joint]:.1f}° on "
                f"{worst_joint} > {tracking_error:.1f}°"
            )

        remaining = {
            joint: abs(target[f"{joint}.pos"] - command[f"{joint}.pos"])
            for joint in JOINTS
        }
        final_arm_errors = {
            joint: abs(target[f"{joint}.pos"] - measured[joint])
            for joint in JOINTS
            if joint != "gripper"
        }
        if (
            max(remaining.values()) < 0.05
            and max(final_arm_errors.values()) <= final_error
        ):
            print("\n白臂初始姿态对齐完成。")
            return command

        elapsed = loop_started - started
        if elapsed - last_print >= 0.5:
            summary = " ".join(
                f"{joint}={remaining[joint]:.1f}" for joint in JOINTS
            )
            print(f"\r对齐剩余: {summary}", end="", flush=True)
            last_print = elapsed

        sleep_s = period - (time.monotonic() - loop_started)
        if sleep_s > 0:
            time.sleep(sleep_s)


def key_available() -> bool:
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return False
    return sys.stdin.read(1).lower() in {"q", "\x1b"}


def configure_follower_while_torque_off(robot: object) -> None:
    """Apply the normal SO follower settings without re-enabling torque."""
    from lerobot.motors.feetech import OperatingMode

    bus = robot.bus
    bus.disable_torque()
    bus.configure_motors()
    for motor in bus.motors:
        bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
        bus.write("P_Coefficient", motor, 16)
        bus.write("I_Coefficient", motor, 0)
        bus.write("D_Coefficient", motor, 32)
        if motor == "gripper":
            bus.write("Max_Torque_Limit", motor, 500)
            bus.write("Protection_Current", motor, 250)
            bus.write("Overload_Torque", motor, 25)


def install_white_wrist_range_if_safe(robot: object) -> None:
    """Install only wrist-roll limits after proving all other calibration matches."""
    expected = robot.calibration
    actual = robot.bus.read_calibration()
    if set(actual) != set(expected):
        raise RuntimeError("white-arm motor set does not match the cached calibration")

    wrist = "wrist_roll"
    wanted = expected[wrist]
    if (wanted.range_min, wanted.range_max) != (0, 4095):
        raise RuntimeError(
            "refusing calibration install: cached wrist_roll range is not 0..4095"
        )

    unexpected = []
    for joint in JOINTS:
        cached = expected[joint]
        motor = actual[joint]
        if cached.homing_offset != motor.homing_offset:
            unexpected.append(
                f"{joint}.homing_offset cached={cached.homing_offset} motor={motor.homing_offset}"
            )
        if joint != wrist and (
            cached.range_min != motor.range_min or cached.range_max != motor.range_max
        ):
            unexpected.append(
                f"{joint}.range cached=[{cached.range_min},{cached.range_max}] "
                f"motor=[{motor.range_min},{motor.range_max}]"
            )
    if unexpected:
        raise RuntimeError(
            "refusing wrist-only calibration install because other fields differ: "
            + "; ".join(unexpected)
        )

    current = actual[wrist]
    if (current.range_min, current.range_max) == (wanted.range_min, wanted.range_max):
        print("白臂 wrist_roll 电机限位已经是 0..4095；无需写入。")
        return

    print(
        "\n白臂保持松扭矩；将只更新 wrist_roll 电机限位寄存器："
        f"[{current.range_min}, {current.range_max}] -> "
        f"[{wanted.range_min}, {wanted.range_max}]"
    )
    print("其他关节范围和全部 homing_offset 已确认与电机一致。")
    if input("输入 INSTALL 写入这两个限位；其他输入取消：").strip() != "INSTALL":
        raise RuntimeError("wrist-roll calibration install cancelled; torque remained off")

    robot.bus.write("Min_Position_Limit", wrist, wanted.range_min)
    robot.bus.write("Max_Position_Limit", wrist, wanted.range_max)
    if not robot.is_calibrated:
        raise RuntimeError("wrist-roll limits were written but calibration verification failed")
    print("wrist_roll 限位已写入并回读验证；白臂仍为松扭矩。")


def main() -> int:
    args = parse_args()
    raise SystemExit(MOTION_LOCKED_REASON)
    if args.max_delta_deg <= 0 or args.max_gripper_delta <= 0:
        raise SystemExit("motion limits must be positive")
    if (
        args.fps <= 0
        or args.duration_s <= 0
        or args.max_speed_deg_s <= 0
        or args.max_gripper_speed_s <= 0
        or args.align_speed_deg_s <= 0
        or args.align_gripper_speed_s <= 0
        or args.align_timeout_s <= 0
        or args.align_final_error_deg <= 0
        or args.max_align_delta_deg <= 0
    ):
        raise SystemExit("fps, duration and speed limits must be positive")
    if args.start_range_tolerance_ticks < 0:
        raise SystemExit("start-range tolerance must be non-negative")
    if not sys.stdin.isatty():
        raise SystemExit("interactive TTY required; use jetson_robot_exec.sh --interactive")

    try:
        black_port = resolve_port(BOARDS["black"], override=args.black_port)
        white_port = resolve_port(BOARDS["white"], override=args.white_port)
    except PortResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if black_port == white_port:
        raise SystemExit("black and white ports resolved to the same device")

    from lerobot.robots.so_follower.config_so_follower import SO100FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO100Follower

    black = SO100Follower(
        SO100FollowerConfig(
            port=black_port,
            id=args.black_id,
            disable_torque_on_disconnect=True,
        )
    )
    white = SO100Follower(
        SO100FollowerConfig(
            port=white_port,
            id=args.white_id,
            disable_torque_on_disconnect=True,
            max_relative_target=None,
        )
    )

    black_connected = False
    white_connected = False
    saved_terminal = None
    try:
        print(f"黑臂 leader（只读/松扭矩）：{black_port}")
        print(f"白臂 follower（执行）：{white_port}")
        # Connect buses directly. SOFollower.connect() calls configure(), whose
        # torque-disabled context re-enables torque on exit; that is unsuitable
        # for a hand-moved leader and for a follower awaiting confirmation.
        black.bus.connect()
        black_connected = True
        black.bus.disable_torque()
        if not black.is_calibrated:
            raise RuntimeError(
                f"black-arm motor registers do not match {args.black_id} calibration"
            )

        white.bus.connect()
        white_connected = True
        white.bus.disable_torque()
        if not white.is_calibrated:
            if args.install_white_wrist_range:
                install_white_wrist_range_if_safe(white)
            else:
                raise RuntimeError(
                    f"white-arm motor registers do not match {args.white_id} calibration"
                )
        configure_follower_while_torque_off(white)

        white_raw = white.bus.sync_read("Present_Position", normalize=False)
        outside = {}
        near_boundary = {}
        for joint, raw in white_raw.items():
            calibration = white.calibration[joint]
            if raw < calibration.range_min:
                excess = calibration.range_min - raw
            elif raw > calibration.range_max:
                excess = raw - calibration.range_max
            else:
                excess = 0
            if excess > args.start_range_tolerance_ticks:
                outside[joint] = {
                    "raw": int(raw),
                    "allowed": [calibration.range_min, calibration.range_max],
                    "excess": int(excess),
                }
            elif excess:
                near_boundary[joint] = {
                    "raw": int(raw),
                    "allowed": [calibration.range_min, calibration.range_max],
                    "excess": int(excess),
                }
        if outside:
            details = ", ".join(
                f"{joint}: raw={item['raw']} allowed={item['allowed']} "
                f"excess={item['excess']} ticks"
                for joint, item in outside.items()
            )
            raise RuntimeError(
                "white arm is outside its commandable calibrated range while torque is off; "
                f"reposition it manually before following ({details})"
            )
        if near_boundary:
            details = ", ".join(
                f"{joint}: raw={item['raw']} -> allowed={item['allowed']} "
                f"({item['excess']} ticks outside)"
                for joint, item in near_boundary.items()
            )
            print(
                "白臂松扭矩姿态轻微越过标定边界；启动目标将夹回最近边界："
                + details
            )

        black_start = positions(black.get_observation())
        bounds = calibrated_target_bounds(white)
        white_observed_start = positions(white.get_observation())
        clamped_start_action = clamp_to_bounds(
            {f"{joint}.pos": white_observed_start[joint] for joint in JOINTS}, bounds
        )
        white_start = {
            joint: clamped_start_action[f"{joint}.pos"] for joint in JOINTS
        }
        # Seed goals before torque is enabled so the white arm cannot jump.
        white.bus.sync_write("Goal_Position", white_start)

        signs = {joint: (-1.0 if joint in args.invert else 1.0) for joint in JOINTS}
        print("方向：" + ", ".join(f"{j}={'-' if signs[j] < 0 else '+'}" for j in JOINTS))
        if args.absolute_follow:
            alignment_target = absolute_targets(black_start, signs)
            # A one-turn wrist has no unique numerical representation at the
            # -180/+180 boundary. Keep the follower's current physical wrist
            # orientation for alignment, then copy wrap-aware leader deltas.
            alignment_target["wrist_roll.pos"] = white_start["wrist_roll"]
            violations = target_bound_violations(alignment_target, bounds)
            if violations:
                details = ", ".join(
                    f"{joint}: target={value:.1f} allowed=[{lower:.1f},{upper:.1f}]"
                    for joint, (value, lower, upper) in violations.items()
                )
                raise RuntimeError(
                    "black-arm pose cannot be represented by the white calibration; "
                    f"reposition the black arm ({details})"
                )
            align_deltas = {
                joint: alignment_target[f"{joint}.pos"] - white_start[joint]
                for joint in JOINTS
            }
            print("\n绝对跟随模式：白臂将先低速靠齐黑臂的标定关节角。")
            print("关节              黑臂读数      白臂当前      对齐变化")
            for joint in JOINTS:
                unit = "%" if joint == "gripper" else "°"
                leader_value = black_start[joint]
                print(
                    f"{joint:16s} {leader_value:9.1f}{unit} "
                    f"{white_start[joint]:11.1f}{unit} {align_deltas[joint]:+11.1f}{unit}"
                )
            print(
                "注：wrist_roll 是一圈循环关节；初始不追逐 ±180° 数字，"
                "对齐后复制连续旋转增量。"
            )
            excessive = {
                joint: delta
                for joint, delta in align_deltas.items()
                if joint not in {"gripper", "wrist_roll"}
                and abs(delta) > args.max_align_delta_deg
            }
            if excessive:
                details = ", ".join(
                    f"{joint}={delta:+.1f}°" for joint, delta in excessive.items()
                )
                raise RuntimeError(
                    "initial absolute alignment is too large; manually pose the arms "
                    f"closer before retrying ({details})"
                )

            print(
                f"对齐速度：手臂 {args.align_speed_deg_s:.1f}°/s，"
                f"夹爪 {args.align_gripper_speed_s:.1f}/s。"
            )
            print("清空两臂之间与白臂完整对齐路径；保持可立即切断 12V。")
            if input("输入 ALIGN 才给白臂上扭矩并开始低速对齐：").strip() != "ALIGN":
                print("已取消；没有启用白臂扭矩。")
                return 0
            white.bus.enable_torque()
            command = move_to_alignment(
                white,
                {f"{joint}.pos": white_start[joint] for joint in JOINTS},
                alignment_target,
                args.fps,
                args.align_speed_deg_s,
                args.align_gripper_speed_s,
                args.tracking_error_deg,
                args.align_timeout_s,
                args.align_final_error_deg,
            )
            print("白臂正在保持对齐姿态；再次检查两臂周围。")
            if input("输入 FOLLOW 开始绝对姿态实时跟随；其他输入结束：").strip() != "FOLLOW":
                print("已取消实时跟随；正在松开白臂扭矩。")
                return 0
            black_wrist_previous = black_start["wrist_roll"]
            white_wrist_command = alignment_target["wrist_roll.pos"]
        else:
            print("\n相对跟随模式：不对齐初始姿态，只复制黑臂的关节变化量。")
            if args.full_range:
                print("白臂总范围：完整标定范围（没有启动姿态 ±N° 限制）。")
            else:
                print(
                    f"白臂总范围：手臂关节 ±{args.max_delta_deg:.1f}°，"
                    f"夹爪 ±{args.max_gripper_delta:.1f}。"
                )
            print("先托住两条手臂并清空周围；随时按 q/ESC、Ctrl-C 或切断 12V。")
            if input("输入 FOLLOW 才给白臂上扭矩并开始：").strip() != "FOLLOW":
                print("已取消；没有启用白臂扭矩。")
                return 0
            white.bus.enable_torque()
            command = {f"{joint}.pos": white_start[joint] for joint in JOINTS}

        print(
            f"跟随速度限制：手臂 {args.max_speed_deg_s:.1f}°/s，"
            f"夹爪 {args.max_gripper_speed_s:.1f}/s；最长 {args.duration_s:.0f}s。"
        )
        saved_terminal = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        started = time.monotonic()
        period = 1.0 / args.fps
        arm_step = args.max_speed_deg_s / args.fps
        gripper_step = args.max_gripper_speed_s / args.fps
        last_print = 0.0
        while time.monotonic() - started < args.duration_s:
            loop_started = time.monotonic()
            if key_available():
                print("\n收到停止键。")
                break

            black_now = positions(black.get_observation())
            if args.absolute_follow:
                target = absolute_targets(black_now, signs)
                wrist_step = wrapped_delta_deg(
                    black_now["wrist_roll"], black_wrist_previous
                )
                black_wrist_previous = black_now["wrist_roll"]
                white_wrist_command += signs["wrist_roll"] * wrist_step
                target["wrist_roll.pos"] = white_wrist_command
                violations = target_bound_violations(target, bounds)
                if violations:
                    details = ", ".join(
                        f"{joint}={value:.1f} outside [{lower:.1f},{upper:.1f}]"
                        for joint, (value, lower, upper) in violations.items()
                    )
                    raise RuntimeError(f"absolute leader target left white range: {details}")
            else:
                target = bounded_relative_targets(
                    black_now,
                    black_start,
                    white_start,
                    signs,
                    args.max_delta_deg,
                    args.max_gripper_delta,
                    args.full_range,
                )
                target = clamp_to_bounds(target, bounds)
            command = slew_toward(command, target, arm_step, gripper_step)
            white.bus.sync_write(
                "Goal_Position",
                {key.removesuffix(".pos"): value for key, value in command.items()},
            )
            white_now = positions(white.get_observation())
            arm_errors = {
                joint: abs(float(command[f"{joint}.pos"]) - white_now[joint])
                for joint in JOINTS
                if joint != "gripper"
            }
            worst_joint = max(arm_errors, key=arm_errors.get)
            if arm_errors[worst_joint] > args.tracking_error_deg:
                raise RuntimeError(
                    f"tracking error {arm_errors[worst_joint]:.1f}° on {worst_joint} "
                    f"> {args.tracking_error_deg:.1f}°"
                )

            elapsed = time.monotonic() - started
            if elapsed - last_print >= 0.5:
                if args.absolute_follow:
                    status_text = " ".join(
                        f"{joint}={float(command[f'{joint}.pos']):+.1f}"
                        for joint in JOINTS
                    )
                    label = "white absolute"
                else:
                    status_text = " ".join(
                        f"{joint}={float(command[f'{joint}.pos']) - white_start[joint]:+.1f}"
                        for joint in JOINTS
                    )
                    label = "white delta"
                print(f"\r{elapsed:5.1f}s {label}: {status_text}", end="", flush=True)
                last_print = elapsed

            sleep_s = period - (time.monotonic() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
        print("\n测试结束；正在松开白臂扭矩。")
        return 0
    except KeyboardInterrupt:
        print("\nCtrl-C：停止并松扭矩。")
        return 130
    finally:
        if saved_terminal is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_terminal)
        if white_connected:
            white.disconnect()
        if black_connected:
            black.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
