"""
Unified communication protocol for robot hosts.

This defines the standard message format and encoding/decoding functions
for communication between the remote core and robot hosts.
"""

import json
import base64
import time
from typing import Dict, Any, Optional, List
from enum import Enum


class CommandType(Enum):
    """Standard command types for robot control."""
    MOVE = "move"
    STOP = "stop"
    RESET = "reset"
    GET_STATE = "get_state"
    SET_ARM_JOINT = "set_arm_joint"
    SET_CAMERA_POSITION = "set_camera_position"
    RESET_CAMERA = "reset_camera"
    PING = "ping"


class ResponseType(Enum):
    """Standard response types from robot hosts."""
    SUCCESS = "success"
    ERROR = "error"
    STATE = "state"
    VIDEO = "video"
    PONG = "pong"


class RobotProtocol:
    """Unified protocol for robot communication."""

    @staticmethod
    def encode_command(command_type: CommandType, data: Optional[Dict[str, Any]] = None) -> bytes:
        """Encode a command message for sending to robot host.

        Args:
            command_type: Type of command to send
            data: Optional command data/parameters

        Returns:
            Encoded message as bytes
        """
        message = {
            "type": "command",
            "command": command_type.value,
            "data": data or {},
            "timestamp": time.time()
        }
        return json.dumps(message).encode('utf-8')

    @staticmethod
    def decode_response(raw_data: bytes) -> Dict[str, Any]:
        """Decode response message from robot host.

        Args:
            raw_data: Raw bytes received from robot

        Returns:
            Decoded message dictionary
        """
        try:
            message = json.loads(raw_data.decode('utf-8'))
            return message
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return {
                "type": "error",
                "response": ResponseType.ERROR.value,
                "message": f"Failed to decode response: {e}",
                "timestamp": time.time()
            }

    @staticmethod
    def encode_response(response_type: ResponseType, data: Optional[Dict[str, Any]] = None) -> bytes:
        """Encode a response message for sending from robot host.

        Args:
            response_type: Type of response
            data: Response data

        Returns:
            Encoded message as bytes
        """
        message = {
            "type": "response",
            "response": response_type.value,
            "data": data or {},
            "timestamp": time.time()
        }
        return json.dumps(message).encode('utf-8')

    @staticmethod
    def decode_command(raw_data: bytes) -> Dict[str, Any]:
        """Decode command message from remote core.

        Args:
            raw_data: Raw bytes received from remote core

        Returns:
            Decoded command dictionary
        """
        try:
            message = json.loads(raw_data.decode('utf-8'))
            return message
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return {
                "type": "error",
                "command": "invalid",
                "message": f"Failed to decode command: {e}",
                "timestamp": time.time()
            }

    @staticmethod
    def encode_move_command(direction: str, speed: float = 1.0) -> bytes:
        """Encode a move command.

        Args:
            direction: Movement direction (forward, backward, left, right, etc.)
            speed: Movement speed (0.0 to 1.0)

        Returns:
            Encoded move command
        """
        return RobotProtocol.encode_command(
            CommandType.MOVE,
            {"direction": direction, "speed": speed}
        )

    @staticmethod
    def encode_arm_joint_command(arm: str, joint_index: int, angle: float) -> bytes:
        """Encode an arm joint control command.

        Args:
            arm: Arm identifier (e.g., "left", "right")
            joint_index: Joint index (0-based)
            angle: Target joint angle in radians

        Returns:
            Encoded joint command
        """
        return RobotProtocol.encode_command(
            CommandType.SET_ARM_JOINT,
            {"arm": arm, "joint_index": joint_index, "angle": angle}
        )

    @staticmethod
    def encode_camera_command(position: List[float], target: Optional[List[float]] = None) -> bytes:
        """Encode a camera position command.

        Args:
            position: Camera position [x, y, z]
            target: Optional camera target [x, y, z]

        Returns:
            Encoded camera command
        """
        data = {"position": position}
        if target:
            data["target"] = target
        return RobotProtocol.encode_command(CommandType.SET_CAMERA_POSITION, data)

    @staticmethod
    def encode_video_frame(frame_data: bytes, width: int, height: int,
                          quality: int = 80, camera_id: str = "main") -> bytes:
        """Encode a video frame for transmission.

        Args:
            frame_data: Raw image data (JPEG encoded)
            width: Frame width
            height: Frame height
            quality: JPEG quality
            camera_id: Camera identifier

        Returns:
            Encoded video message
        """
        frame_b64 = base64.b64encode(frame_data).decode('utf-8')
        data = {
            "frame": frame_b64,
            "width": width,
            "height": height,
            "quality": quality,
            "camera_id": camera_id,
            "format": "jpeg"
        }
        return RobotProtocol.encode_response(ResponseType.VIDEO, data)

    @staticmethod
    def decode_video_frame(message: Dict[str, Any]) -> Optional[bytes]:
        """Decode video frame from message.

        Args:
            message: Decoded video message

        Returns:
            Raw JPEG frame data or None if invalid
        """
        try:
            if message.get("response") != ResponseType.VIDEO.value:
                return None

            data = message.get("data", {})
            frame_b64 = data.get("frame")
            if not frame_b64:
                return None

            return base64.b64decode(frame_b64)
        except Exception:
            return None

    @staticmethod
    def encode_robot_state(position: Dict[str, float], rotation: Dict[str, float],
                          arm_joints: Dict[str, List[float]], status: str = "connected") -> bytes:
        """Encode robot state information.

        Args:
            position: Robot position {x, y, z}
            rotation: Robot rotation {roll, pitch, yaw}
            arm_joints: Arm joint positions {"left": [...], "right": [...]}
            status: Robot status string

        Returns:
            Encoded state message
        """
        data = {
            "position": position,
            "rotation": rotation,
            "arm_joints": arm_joints,
            "status": status,
            "timestamp": time.time()
        }
        return RobotProtocol.encode_response(ResponseType.STATE, data)

    @staticmethod
    def is_valid_message(message: Dict[str, Any]) -> bool:
        """Check if a message has valid structure.

        Args:
            message: Decoded message dictionary

        Returns:
            True if message is valid
        """
        required_fields = ["type", "timestamp"]

        if not all(field in message for field in required_fields):
            return False

        if message["type"] == "command":
            return "command" in message
        elif message["type"] == "response":
            return "response" in message

        return False

    @staticmethod
    def create_error_response(error_message: str) -> bytes:
        """Create a standard error response.

        Args:
            error_message: Error description

        Returns:
            Encoded error response
        """
        return RobotProtocol.encode_response(
            ResponseType.ERROR,
            {"message": error_message}
        )

    @staticmethod
    def create_success_response(data: Optional[Dict[str, Any]] = None) -> bytes:
        """Create a standard success response.

        Args:
            data: Optional success data

        Returns:
            Encoded success response
        """
        return RobotProtocol.encode_response(ResponseType.SUCCESS, data or {})