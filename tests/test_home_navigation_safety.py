import unittest
from pathlib import Path

from tools.base_emergency_stop import disable_each_wheel
from tools.nav2_supervised_base_execute import (
    LiveRgbdOdom,
    WheelPoseTracker,
    dock_heading_phase,
    final_yaw_progress_baseline,
    holonomic_path_command,
    require_dock_arrival_yaw,
    validate_stationary_visual_agreement,
    validate_route_envelope,
)
from tools.resolve_home_workspace_pose import resolve_pose
from tools.resolve_home_navigation_route import resolve_route
from tools.base_relative_pose_execute import relative_pose_command
from tools.base_relative_pose_execute import validate_args as validate_relative_pose_args


class StopAttemptsTest(unittest.TestCase):
    def test_one_exception_does_not_skip_other_wheels(self):
        class Packet:
            def __init__(self):
                self.ids = []

            def write1ByteTxRx(self, _port, motor_id, address, value):
                self.ids.append(motor_id)
                self.assertions = (address, value)
                if motor_id == 7:
                    raise RuntimeError("bus timeout")
                return 0, 0

        packet = Packet()
        errors = disable_each_wheel(packet, object(), [7, 8, 9], 40, 0)
        self.assertEqual(packet.ids, [7, 8, 9])
        self.assertEqual(packet.assertions, (40, 0))
        self.assertEqual(len(errors), 1)

    def test_transport_error_does_not_skip_other_wheels(self):
        class Packet:
            def __init__(self):
                self.ids = []

            def write1ByteTxRx(self, _port, motor_id, _address, _value):
                self.ids.append(motor_id)
                return (-6, 0) if motor_id == 8 else (0, 0)

        packet = Packet()
        errors = disable_each_wheel(packet, object(), [7, 8, 9], 40, 0)
        self.assertEqual(packet.ids, [7, 8, 9])
        self.assertEqual(len(errors), 1)
        self.assertIn("ID 8", errors[0])


class LatestVisualPoseTest(unittest.TestCase):
    def test_rgbd_subscription_retains_only_latest_pose(self):
        class Node:
            def create_subscription(self, message_type, topic, callback, depth):
                self.arguments = (message_type, topic, callback, depth)
                return object()

        node = Node()
        LiveRgbdOdom(node, object())
        self.assertEqual(node.arguments[1], "/rtabmap/odom")
        self.assertEqual(node.arguments[3], 1)


class RouteStartupPriorTest(unittest.TestCase):
    def test_both_continuous_routes_supply_direction_specific_start_prior(self):
        root = Path(__file__).resolve().parents[1]
        for script_name, pose_id in (
            ("jetson_home_navigate_table_to_sofa_continuous.sh", "right_a.work_pose"),
            ("jetson_home_navigate_sofa_to_table_continuous.sh", "right_c.work_pose"),
        ):
            text = (root / "scripts" / script_name).read_text(encoding="utf-8")
            self.assertIn(f"--pose-id {pose_id} --tsv", text)
            self.assertIn('--initial-map-pose-x "$start_x"', text)
            self.assertIn('--initial-map-pose-y "$start_y"', text)
            self.assertIn('--initial-map-pose-yaw-deg "$start_yaw"', text)
            self.assertIn('--expected-start-x "$start_x"', text)


class DockHeadingHysteresisTest(unittest.TestCase):
    def test_recorded_arrival_outside_two_degrees_reenters_alignment(self):
        self.assertEqual(dock_heading_phase("translate", -2.49, 2.0, 5.0), "translate")
        self.assertEqual(
            dock_heading_phase(
                "translate", -3.437, 2.0, 5.0,
                position_reached=True, arrival_tolerance_deg=2.0,
            ),
            "align",
        )

    def test_arrival_inside_two_degrees_can_complete_without_realign(self):
        self.assertEqual(
            dock_heading_phase(
                "translate", -1.9, 2.0, 5.0,
                position_reached=True, arrival_tolerance_deg=2.0,
            ),
            "translate",
        )

    def test_arrival_boundary_and_invalid_yaw(self):
        for yaw in (-2.0, 0.0, 2.0):
            require_dock_arrival_yaw(yaw, 2.0)
        for yaw in (-2.001, 2.001, float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                require_dock_arrival_yaw(yaw, 2.0)

    def test_visual_yaw_noise_does_not_toggle_translation_at_entry_threshold(self):
        self.assertEqual(dock_heading_phase("align", 1.9, 2.0, 5.0), "translate")
        self.assertEqual(dock_heading_phase("translate", 2.1, 2.0, 5.0), "translate")
        self.assertEqual(dock_heading_phase("translate", 4.9, 2.0, 5.0), "translate")
        self.assertEqual(dock_heading_phase("translate", 5.1, 2.0, 5.0), "align")


class HolonomicPathCommandTest(unittest.TestCase):
    def test_sideways_map_motion_does_not_turn_chassis_to_path_tangent(self):
        vx, vy, angular = holonomic_path_command(0.0, 1.0, 0.0, 0.0, 0.04, 12.0, 5.0)
        self.assertAlmostEqual(vx, 0.0, places=6)
        self.assertAlmostEqual(vy, 0.04, places=6)
        self.assertAlmostEqual(angular, 0.0, places=6)

    def test_small_heading_error_is_corrected_while_translating(self):
        vx, vy, angular = holonomic_path_command(0.0, 1.0, 2.0, 0.0, 0.04, 12.0, 5.0)
        self.assertGreater(abs(vx) + abs(vy), 0.0)
        self.assertAlmostEqual(angular, -1.2, places=6)

    def test_large_heading_error_pauses_translation(self):
        vx, vy, angular = holonomic_path_command(0.0, 1.0, 10.0, 0.0, 0.04, 12.0, 5.0)
        self.assertEqual((vx, vy), (0.0, 0.0))
        self.assertAlmostEqual(angular, -6.0, places=6)


class RelativePoseCommandTest(unittest.TestCase):
    def test_sofa_exit_starts_with_backward_and_lateral_motion(self):
        vx, vy, angular, distance, yaw_error = relative_pose_command(
            0.0, 0.0, 0.0, -0.1835, 0.0330, -3.786, 0.04, 8.0, 0.015
        )
        self.assertLess(vx, 0.0)
        self.assertGreater(vy, 0.0)
        self.assertLess(angular, 0.0)
        self.assertAlmostEqual(distance, 0.1864, places=3)
        self.assertAlmostEqual(yaw_error, -3.786, places=3)

    def test_cross_workspace_relative_envelope_accepts_sub_meter_move(self):
        class Args:
            x_m = -0.0866
            y_m = 0.8830
            yaw_deg = 0.574
            max_linear_mps = 0.04
            max_angular_deg_s = 8.0
            max_runtime_s = 35.0
            position_tolerance_m = 0.02
            yaw_tolerance_deg = 1.0
            max_travel_m = 1.10

        validate_relative_pose_args(Args())


class ContinuousRouteEnvelopeTest(unittest.TestCase):
    def test_three_meter_route_is_allowed(self):
        validate_route_envelope(3.0, 3.25, 180.0)

    def test_route_limits_fail_closed(self):
        for limits in ((3.001, 3.25, 180.0), (3.0, 3.251, 180.0), (3.0, 3.25, 180.1)):
            with self.assertRaises(ValueError):
                validate_route_envelope(*limits)


class PostRotationVisualGateTest(unittest.TestCase):
    def test_accepts_stable_agreement_without_changing_wheel_pose(self):
        wheel = (0.04, -1.48, 90.0)
        disagreement = validate_stationary_visual_agreement(
            wheel, (0.06, -1.49, 94.0), 0.12, 15.0
        )
        self.assertAlmostEqual(disagreement[0], (0.0005) ** 0.5)
        self.assertEqual(disagreement[1], 4.0)
        self.assertEqual(wheel, (0.04, -1.48, 90.0))

    def test_rejects_false_xy_reanchor_after_rotation(self):
        with self.assertRaisesRegex(RuntimeError, "refusing visual XY re-anchor"):
            validate_stationary_visual_agreement(
                (0.04, -1.48, 90.0), (0.14, -1.686, 106.0), 0.12, 15.0
            )

    def test_intentional_settle_resets_timebase_without_changing_pose(self):
        tracker = WheelPoseTracker((0.04, -1.48, 90.0))
        tracker.update({7: 0, 8: 0, 9: 0}, 1.0)
        tracker.reset_stopped_timebase({7: 0, 8: 0, 9: 0}, 4.0)
        self.assertEqual(tracker.update({7: 0, 8: 0, 9: 0}, 4.2), (0.04, -1.48, 90.0))

    def test_timebase_reset_rejects_moving_wheel(self):
        tracker = WheelPoseTracker((0.0, 0.0, 0.0))
        with self.assertRaisesRegex(RuntimeError, "not stationary"):
            tracker.reset_stopped_timebase({7: 101, 8: 0, 9: 0}, 4.0)


class FinalYawProgressTest(unittest.TestCase):
    def test_entering_goal_radius_resets_large_final_yaw_error(self):
        best, reset = final_yaw_progress_baseline(False, True, -86.0, 4.0)
        self.assertEqual(best, 86.0)
        self.assertTrue(reset)

    def test_remaining_inside_does_not_reset_each_loop(self):
        best, reset = final_yaw_progress_baseline(True, True, -70.0, 72.0)
        self.assertEqual(best, 72.0)
        self.assertFalse(reset)


class NamedWorkspacePoseTest(unittest.TestCase):
    def test_resolves_recorded_sofa_predock(self):
        pose = resolve_pose(Path("configs/nav2/home_workspaces_20260902T194820Z.yaml"), "right_c.predock_pose")
        self.assertEqual(pose, {"x": 0.044, "y": -1.482, "yaw_deg": -0.689})


class ContinuousNamedRouteTest(unittest.TestCase):
    def test_sofa_to_table_route_preserves_direct_and_guarded_modes(self):
        legs = resolve_route(
            Path("configs/nav2/sofa_to_table_continuous_20260902T194820Z.yaml"),
            Path("configs/nav2/home_workspaces_20260902T194820Z.yaml"),
        )
        self.assertEqual([leg["pose_id"] for leg in legs], [
            "right_c.predock_pose", "right_a.predock_pose",
            "right_a.predock_pose", "right_a.work_pose", "right_a.work_pose"
        ])
        self.assertEqual([leg["wheel_visual_policy"] for leg in legs], [
            "bounded", "liveness", "bounded", "bounded", "bounded"
        ])
        self.assertEqual([leg["dock_entry_distance_m"] for leg in legs], [0.5, 0.0, 0.5, 0.5, 0.5])
        self.assertEqual([leg["append_exact_goal"] for leg in legs], [False, False, False, True, True])
        self.assertEqual([leg["motion_mode"] for leg in legs], [
            "forward_path", "holonomic_path", "holonomic_path",
            "forward_path", "holonomic_path"
        ])
        self.assertEqual([leg["preplan_localization_s"] for leg in legs], [0, 0, 30, 0, 30])

    def test_table_to_sofa_route_preserves_direct_and_guarded_modes(self):
        legs = resolve_route(
            Path("configs/nav2/table_to_sofa_continuous_20260902T194820Z.yaml"),
            Path("configs/nav2/home_workspaces_20260902T194820Z.yaml"),
        )
        self.assertEqual([leg["pose_id"] for leg in legs], [
            "right_a.predock_pose", "right_c.predock_pose",
            "right_c.predock_pose", "right_c.work_pose", "right_c.work_pose"
        ])
        self.assertEqual([leg["wheel_visual_policy"] for leg in legs], [
            "bounded", "liveness", "bounded", "bounded", "bounded"
        ])
        self.assertEqual([leg["dock_entry_distance_m"] for leg in legs], [0.5, 0.0, 0.5, 0.5, 0.5])
        self.assertEqual([leg["append_exact_goal"] for leg in legs], [False, False, False, True, True])
        self.assertEqual([leg["motion_mode"] for leg in legs], [
            "forward_path", "holonomic_path", "holonomic_path",
            "forward_path", "holonomic_path"
        ])
        self.assertEqual([leg["preplan_localization_s"] for leg in legs], [0, 0, 30, 0, 30])


if __name__ == "__main__":
    unittest.main()
