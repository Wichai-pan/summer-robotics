#!/usr/bin/env python3
"""
XLeRobot ManiSkill Simulation Host with Remote Control
Simple implementation following KISS principle
"""

from pathlib import Path
import sys

# Ensure local ManiSkill agents are importable when running directly
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# Import the XLeRobot agents to register them (MUST be before other ManiSkill imports)
from agents.xlerobot import xlerobot_single

# Now import other modules
import signal
import json
import queue
import threading
import time
import base64
import logging
from typing import Optional, Dict, Any, Tuple

import cv2
import numpy as np
import zmq
import gymnasium as gym

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


CMD_ENDPOINT = "tcp://*:5555"
DATA_ENDPOINT = "tcp://*:5556"
CMD_QUEUE_MAXSIZE = 100
RESPONSE_QUEUE_MAXSIZE = 50
ZMQ_TIMEOUT_MS = 100
STATE_PUSH_INTERVAL = 0.05  # 20 Hz
VIDEO_PUSH_INTERVAL = 0.1   # 10 Hz
CONTROL_LOOP_HZ = 60
LINEAR_SCALE = 0.1
ROTATION_SCALE = 0.05
NETWORK_IDLE_SLEEP = 0.001


def convert_tensor_to_numpy_image(tensor_image: Any) -> np.ndarray:
    """Return an RGB `uint8` numpy image regardless of incoming tensor type."""

    if hasattr(tensor_image, "cpu"):
        image = tensor_image.cpu().numpy()
    elif hasattr(tensor_image, "numpy"):
        image = tensor_image.numpy()
    else:
        image = np.asarray(tensor_image)

    if image.ndim == 4:
        image = image[0]

    if image.dtype in (np.float32, np.float64):
        image = image.astype(np.float32)
        max_val = float(image.max(initial=0.0)) if hasattr(image, "max") else float(np.max(image))
        if max_val <= 1.0:
            image *= 255.0
        image = image.astype(np.uint8)
    else:
        image = image.astype(np.uint8)

    if image.shape[-1] == 4:
        image = image[..., :3]

    return image


class XLeRobotSimHost:
    """Simple ManiSkill simulation host with remote control capability"""

    @staticmethod
    def _extract_command(command: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        """Return the command keyword and payload regardless of protocol variant."""
        if not command:
            return None, {}

        if command.get("type") == "command":
            data = command.get("data", {})
            return command.get("command"), data if isinstance(data, dict) else {}

        data = command.get("data", {})
        return command.get("command"), data if isinstance(data, dict) else {}

    def __init__(self):
        # === Simple communication: Only Queue + Event ===
        self.cmd_queue = queue.Queue(maxsize=CMD_QUEUE_MAXSIZE)
        self.response_queue = queue.Queue(maxsize=RESPONSE_QUEUE_MAXSIZE)
        self.shutdown_event = threading.Event()

        # === ManiSkill components (main thread only) ===
        self.env = None
        self.robot = None
        self.action = None
        self.target_joints = None
        self.obs = None

        # === Control state ===
        self.current_x_arm1 = 0.247
        self.current_y_arm1 = -0.023
        self.current_x_arm2 = 0.247
        self.current_y_arm2 = -0.023
        self.pitch_arm1 = 0.0
        self.pitch_arm2 = 0.0

        # === Control parameters ===
        self.joint_step = 0.01
        self.ee_step = 0.005
        self.p_gain = np.ones(16)
        self.setup_gains()

        # === Threading ===
        self.network_thread = None

        # Setup signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("XLeRobot Simulation Host initialized")

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM for clean shutdown"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown_event.set()

    def setup_gains(self):
        """Setup proportional control gains"""
        self.p_gain[0] = 2.0      # Base forward/backward
        self.p_gain[1] = 0.5      # Base rotation
        self.p_gain[2:7] = 1.0    # First arm
        self.p_gain[7:12] = 1.0   # Second arm
        self.p_gain[12:14] = 0.05 # Grippers
        self.p_gain[14:16] = 2.0  # Head motors

    def initialize_simulation(self) -> bool:
        """Initialize ManiSkill simulation (main thread only for OpenGL safety)"""
        try:
            logger.info("Initializing ManiSkill simulation...")

            env_kwargs = dict(
                obs_mode="state",
                control_mode="pd_joint_delta_pos",
                render_mode="human",
                robot_uids="xlerobot_single",
                num_envs=1,
                sim_backend="auto",
            )

            self.env = gym.make("PushCube-v1", **env_kwargs)
            self.obs, _ = self.env.reset(seed=2022, options=dict(reconfigure=True))

            # Get robot instance
            if hasattr(self.env.unwrapped, "agent"):
                self.robot = self.env.unwrapped.agent.robot
            else:
                self.robot = None
                logger.warning("Robot instance not found")

            # Initialize action space
            self.action = np.zeros(self.env.action_space.shape)
            self.target_joints = np.zeros_like(self.action)

            # Print action space info for debugging
            logger.info(f"Action space shape: {self.action.shape}")
            logger.info(f"Action space: {self.env.action_space}")

            # Set initial pose (only if action space is large enough)
            if len(self.target_joints) > 6:
                self.target_joints[6] = 1.57   # First arm wrist
            if len(self.target_joints) > 11:
                self.target_joints[11] = 1.57  # Second arm wrist

            logger.info("ManiSkill simulation initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize simulation: {e}")
            return False

    def network_communication_thread(self):
        """Network thread - pure ZeroMQ send/receive"""
        logger.info("Starting network communication thread...")

        context = zmq.Context.instance()
        cmd_socket = None
        data_socket = None

        try:
            # Setup ZeroMQ sockets
            cmd_socket = context.socket(zmq.PULL)
            cmd_socket.setsockopt(zmq.CONFLATE, 1)
            cmd_socket.setsockopt(zmq.RCVTIMEO, ZMQ_TIMEOUT_MS)
            cmd_socket.bind(CMD_ENDPOINT)

            data_socket = context.socket(zmq.PUSH)
            data_socket.setsockopt(zmq.CONFLATE, 1)
            data_socket.setsockopt(zmq.SNDTIMEO, ZMQ_TIMEOUT_MS)
            data_socket.bind(DATA_ENDPOINT)

            logger.info("Network sockets bound (%s commands, %s telemetry)", CMD_ENDPOINT, DATA_ENDPOINT)

            while not self.shutdown_event.is_set():
                # Receive commands (non-blocking)
                try:
                    cmd_data = cmd_socket.recv_string(zmq.NOBLOCK)
                    command = json.loads(cmd_data)
                    self.cmd_queue.put_nowait(command)
                    logger.debug(f"Received command: {command.get('command', 'unknown')}")
                except zmq.Again:
                    pass  # No data available
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON received: {e}")
                except queue.Full:
                    logger.warning("Command queue full, dropping command")

                # Send responses (non-blocking)
                try:
                    response = self.response_queue.get_nowait()
                    data_socket.send_string(json.dumps(response), zmq.NOBLOCK)
                    logger.debug(f"Sent response: {response.get('response', 'unknown')}")
                except queue.Empty:
                    pass  # No data to send
                except zmq.Again:
                    # Send failed, put back in queue if possible
                    try:
                        self.response_queue.put_nowait(response)
                    except queue.Full:
                        logger.warning("Response queue full, dropping response")

                time.sleep(NETWORK_IDLE_SLEEP)  # Small delay to prevent high CPU usage

        except Exception as e:
            logger.error(f"Network communication error: {e}")
        finally:
            if cmd_socket is not None:
                cmd_socket.close(0)
            if data_socket is not None:
                data_socket.close(0)
            logger.info("Network communication thread stopped")

    def process_commands(self):
        """Process command queue (main thread)"""
        while not self.cmd_queue.empty():
            try:
                command = self.cmd_queue.get_nowait()
                self.handle_command(command)
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Command processing error: {e}")

    def handle_command(self, command: Dict[str, Any]):
        """Handle individual command (compatible with unified protocol)"""
        cmd_type, data = self._extract_command(command)
        if not cmd_type:
            logger.warning("Received command without type")
            return

        try:
            if cmd_type == "move":
                direction = data.get("direction", "stop")
                speed = data.get("speed", 1.0)
                self.handle_move_command(direction, speed)

            elif cmd_type == "reset":
                self.reset_robot_state()

            elif cmd_type == "ping":
                self.send_response("pong", {"timestamp": time.time()})

            elif cmd_type == "get_state":
                state = self.get_robot_state()
                self.send_response("state", state)

            else:
                logger.warning(f"Unknown command: {cmd_type}")

        except Exception as e:
            logger.error(f"Error handling command {cmd_type}: {e}")

    def handle_move_command(self, direction: str, speed: float):
        """Handle movement command with proper stop handling"""
        if self.action is None or len(self.action) < 2:
            logger.debug("Movement command ignored because action vector is not ready")
            return

        clamped_speed = max(0.0, min(1.0, speed))

        if direction == "forward":
            self.action[0] = clamped_speed * LINEAR_SCALE
        elif direction == "backward":
            self.action[0] = -clamped_speed * LINEAR_SCALE
        elif direction in ("left", "rotate_left"):
            self.action[1] = clamped_speed * ROTATION_SCALE
        elif direction in ("right", "rotate_right"):
            self.action[1] = -clamped_speed * ROTATION_SCALE
        elif direction == "stop":
            self.action[0] = 0.0
            self.action[1] = 0.0
        else:
            logger.warning(f"Unknown move direction received: {direction}")

    def reset_robot_state(self):
        """Reset robot to initial state"""
        if self.action is not None:
            self.action = np.zeros_like(self.action)
        if self.target_joints is not None:
            self.target_joints = np.zeros_like(self.target_joints)

        # Reset end effector positions
        self.current_x_arm1 = 0.247
        self.current_y_arm1 = -0.023
        self.current_x_arm2 = 0.247
        self.current_y_arm2 = -0.023
        self.pitch_arm1 = 0.0
        self.pitch_arm2 = 0.0

        # Set initial wrist positions (only if action space is large enough)
        if self.target_joints is not None:
            if len(self.target_joints) > 6:
                self.target_joints[6] = 1.57
            if len(self.target_joints) > 11:
                self.target_joints[11] = 1.57

        logger.info("Robot state reset to initial position")

    def get_current_joints(self):
        """Get current joint positions (reuse mapping logic)"""
        if self.robot is None:
            return np.zeros(16, dtype=np.float32)

        try:
            full_joints = self.robot.get_qpos()
            if hasattr(full_joints, 'numpy'):
                full_joints = full_joints.numpy()
            if full_joints.ndim > 1:
                full_joints = full_joints.squeeze()

            # Joint mapping (simplified from existing logic)
            mapped_joints = np.zeros(16, dtype=np.float32)
            if len(full_joints) >= 15:
                mapped_joints[0] = full_joints[0]   # Base X position
                mapped_joints[1] = full_joints[2]   # Base rotation

                # First arm: [3,6,9,11,13] → [2,3,4,5,6]
                mapped_joints[2] = full_joints[3]
                mapped_joints[3] = full_joints[6]
                mapped_joints[4] = full_joints[9]
                mapped_joints[5] = full_joints[11]
                mapped_joints[6] = full_joints[13]

                # Second arm: [4,7,10,12,14] → [7,8,9,10,11]
                mapped_joints[7] = full_joints[4]
                mapped_joints[8] = full_joints[7]
                mapped_joints[9] = full_joints[10]
                mapped_joints[10] = full_joints[12]
                mapped_joints[11] = full_joints[14]

                # Grippers and head
                if len(full_joints) >= 17:
                    mapped_joints[12] = full_joints[15]  # Gripper 1
                    mapped_joints[13] = full_joints[16]  # Gripper 2
                    mapped_joints[14] = full_joints[5]   # Head motor 1
                    mapped_joints[15] = full_joints[8]   # Head motor 2

            return mapped_joints

        except Exception as e:
            logger.error(f"Error getting joint positions: {e}")
            return np.zeros(16, dtype=np.float32)

    def update_control_action(self):
        """Update control action using P controller (skip base movement)"""
        if self.robot is None:
            return

        try:
            current_joints = self.get_current_joints()

            # P controller for arm joints only (skip base movement: action[0] and action[1])
            # action[0] = forward/backward, action[1] = rotation - controlled directly by commands
            for i in range(2, len(self.action)):
                if i < len(current_joints) and i < len(self.target_joints):
                    error = self.target_joints[i] - current_joints[i]
                    self.action[i] = self.p_gain[i] * error

        except Exception as e:
            logger.error(f"Error updating control action: {e}")

    def get_robot_state(self) -> Dict[str, Any]:
        """Get current robot state"""
        try:
            current_joints = self.get_current_joints()

            return {
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": float(current_joints[1])},
                "arm_joints": {
                    "left": current_joints[2:7].tolist(),
                    "right": current_joints[7:12].tolist()
                },
                "base_joints": current_joints[0:2].tolist(),
                "grippers": current_joints[12:14].tolist(),
                "head_motors": current_joints[14:16].tolist(),
                "status": "connected",
                "timestamp": time.time()
            }
        except Exception as e:
            logger.error(f"Error getting robot state: {e}")
            return {"status": "error", "message": str(e), "timestamp": time.time()}

    def get_video_frame(self) -> Optional[str]:
        """Get video frame from robot's virtual cameras using correct camera API"""
        if self.env is None:
            return None

        try:
            # Use correct camera API instead of get_sensor_images()
            base_env = self.env.unwrapped
            scene = base_env.scene

            # Update renderer with sensors
            scene.update_render(update_sensors=True, update_human_render_cameras=False)

            # Prioritize head camera first, then arm camera
            camera_priority = ["fetch_head", "fetch_right_arm_camera"]

            for camera_name in camera_priority:
                if camera_name in scene.sensors:
                    camera = scene.sensors[camera_name]

                    # Capture current frame
                    camera.capture()

                    # Get RGB observation
                    data = camera.get_obs(rgb=True, depth=False, segmentation=False)

                    if "rgb" in data:
                        # Convert tensor to numpy using our helper function
                        frame = convert_tensor_to_numpy_image(data["rgb"])

                        # Convert RGB to BGR for OpenCV
                        if frame.shape[-1] == 3:
                            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                        # Encode as JPEG
                        success, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if success:
                            logger.debug(f"Captured frame from {camera_name}: {frame.shape}")
                            return base64.b64encode(buffer).decode('utf-8')

            # Fallback: try any available camera
            for camera_name, camera in scene.sensors.items():
                try:
                    camera.capture()
                    data = camera.get_obs(rgb=True, depth=False, segmentation=False)

                    if "rgb" in data:
                        frame = convert_tensor_to_numpy_image(data["rgb"])

                        # Convert RGB to BGR for OpenCV
                        if frame.shape[-1] == 3:
                            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                        success, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if success:
                            logger.debug(f"Captured frame from fallback camera {camera_name}: {frame.shape}")
                            return base64.b64encode(buffer).decode('utf-8')
                except Exception:
                    continue  # Skip cameras that don't support RGB

            logger.warning("No valid RGB camera data found")
            return None

        except Exception as e:
            logger.error(f"Error getting video frame from cameras: {e}")
            return None

    def send_response(self, response_type: str, data: Any):
        """Send response to queue"""
        response = {
            "type": "response",
            "response": response_type,
            "data": data,
            "timestamp": time.time()
        }

        try:
            self.response_queue.put_nowait(response)
        except queue.Full:
            # Queue full, remove oldest and add new
            try:
                self.response_queue.get_nowait()
                self.response_queue.put_nowait(response)
            except queue.Empty:
                pass

    def main_simulation_loop(self):
        """Main simulation loop (main thread - OpenGL safe)"""
        logger.info("Starting main simulation loop...")

        last_state_time = 0.0
        last_video_time = 0.0
        loop_count = 0

        try:
            while not self.shutdown_event.is_set():
                loop_start = time.time()

                # Process commands from network
                self.process_commands()

                # Update control action
                self.update_control_action()

                # Simulation step (must be in main thread for OpenGL)
                self.obs, reward, terminated, truncated, info = self.env.step(self.action)

                # Critical: Render to keep SAPIEN GUI responsive!
                self.env.render()

                now = time.time()

                # Send state periodically (20 Hz)
                if now - last_state_time >= STATE_PUSH_INTERVAL:
                    state = self.get_robot_state()
                    self.send_response("state", state)
                    last_state_time = now

                # Send video periodically (10 Hz)
                if now - last_video_time >= VIDEO_PUSH_INTERVAL:
                    frame = self.get_video_frame()
                    if frame:
                        self.send_response("video", {
                            "frame": frame,
                            "width": 640,
                            "height": 480,
                            "quality": 80,
                            "camera_id": "main",
                            "format": "jpeg"
                        })
                    last_video_time = now

                # Control loop frequency (60 FPS)
                elapsed = time.time() - loop_start
                sleep_time = max((1 / CONTROL_LOOP_HZ) - elapsed, 0.0)
                if sleep_time > 0:
                    time.sleep(sleep_time)

                loop_count += 1

                # Reset if episode ended
                terminated_any = bool(np.asarray(terminated).any())
                truncated_any = bool(np.asarray(truncated).any())
                if terminated_any or truncated_any:
                    self.obs, _ = self.env.reset()

        except Exception as e:
            logger.error(f"Main simulation loop error: {e}")
        finally:
            logger.info(f"Main simulation loop stopped after {loop_count} iterations")

    def run(self):
        """Run the simulation host"""
        logger.info("Starting XLeRobot Simulation Host...")

        try:
            # Initialize simulation
            if not self.initialize_simulation():
                logger.error("Failed to initialize simulation, exiting")
                return 1

            # Start network thread
            self.network_thread = threading.Thread(
                target=self.network_communication_thread,
                name="NetworkThread",
                daemon=True
            )
            self.network_thread.start()
            logger.info("Network thread started")

            # Run main simulation loop
            self.main_simulation_loop()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            self.cleanup()

        return 0

    def cleanup(self):
        """Clean shutdown"""
        logger.info("🧹 Starting cleanup...")

        # Set shutdown event
        self.shutdown_event.set()

        # Wait for network thread to finish
        if self.network_thread and self.network_thread.is_alive():
            self.network_thread.join(timeout=2.0)
            if self.network_thread.is_alive():
                logger.warning("Network thread did not shut down cleanly")

        # Close simulation environment
        if self.env:
            try:
                self.env.close()
                logger.info("Simulation environment closed")
            except Exception as e:
                logger.error(f"Error closing simulation: {e}")

        logger.info("✅ Cleanup complete")


def main():
    """Main entry point"""
    host = XLeRobotSimHost()
    return host.run()


if __name__ == "__main__":
    sys.exit(main())
