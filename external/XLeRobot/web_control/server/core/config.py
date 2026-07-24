"""
Simplified configuration system for unified remote control.

This replaces the complex multi-controller configuration with a clean,
minimal set of essential settings.
"""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class ServerConfig:
    """Simplified server configuration with only essential settings."""

    # Robot Type - determines which host to connect to
    robot_type: str = "maniskill"  # maniskill|mujoco|xlerobot

    # UI Server Configuration - where the web interface runs
    ui_host: str = "0.0.0.0"      # IP to bind web server (0.0.0.0 for all interfaces)
    ui_port: int = 8000           # Port for web interface

    # Robot Host Configuration - where the robot/simulation runs
    robot_host: str = "localhost" # IP of robot host program
    robot_port_cmd: int = 5555    # Command channel port
    robot_port_data: int = 5556   # Data/observation channel port

    # Video Settings - for camera streams
    video_width: int = 640
    video_height: int = 480
    video_fps: int = 30
    video_quality: int = 80       # JPEG quality (1-100)

    # Connection Settings
    connect_timeout_s: int = 5
    polling_timeout_ms: int = 100

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "ServerConfig":
        """Load configuration from environment variables.

        Args:
            env_file: Optional path to .env file to load

        Returns:
            ServerConfig instance with values from environment
        """
        if env_file:
            cls._load_env_file(env_file)

        return cls(
            # Robot Type
            robot_type=os.getenv('ROBOT_TYPE', 'maniskill'),

            # UI Server Config
            ui_host=os.getenv('UI_HOST', '0.0.0.0'),
            ui_port=int(os.getenv('UI_PORT', '8000')),

            # Robot Host Config
            robot_host=os.getenv('ROBOT_HOST', 'localhost'),
            robot_port_cmd=int(os.getenv('ROBOT_PORT_CMD', '5555')),
            robot_port_data=int(os.getenv('ROBOT_PORT_DATA', '5556')),

            # Video Settings
            video_width=int(os.getenv('VIDEO_WIDTH', '640')),
            video_height=int(os.getenv('VIDEO_HEIGHT', '480')),
            video_fps=int(os.getenv('VIDEO_FPS', '30')),
            video_quality=int(os.getenv('VIDEO_QUALITY', '80')),

            # Connection Settings
            connect_timeout_s=int(os.getenv('CONNECT_TIMEOUT_S', '5')),
            polling_timeout_ms=int(os.getenv('POLLING_TIMEOUT_MS', '100')),
        )

    @staticmethod
    def _load_env_file(env_file: str) -> None:
        """Load environment variables from a .env file."""
        env_path = Path(env_file)
        if not env_path.exists():
            print(f"Warning: .env file not found at {env_path}")
            return

        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

    def validate(self) -> None:
        """Validate configuration values."""
        valid_robot_types = ['maniskill', 'mujoco', 'xlerobot']
        if self.robot_type not in valid_robot_types:
            raise ValueError(f"Invalid robot_type: {self.robot_type}. Must be one of {valid_robot_types}")

        if not (1 <= self.ui_port <= 65535):
            raise ValueError(f"Invalid ui_port: {self.ui_port}. Must be between 1-65535")

        if not (1 <= self.robot_port_cmd <= 65535):
            raise ValueError(f"Invalid robot_port_cmd: {self.robot_port_cmd}. Must be between 1-65535")

        if not (1 <= self.robot_port_data <= 65535):
            raise ValueError(f"Invalid robot_port_data: {self.robot_port_data}. Must be between 1-65535")

        if not (1 <= self.video_quality <= 100):
            raise ValueError(f"Invalid video_quality: {self.video_quality}. Must be between 1-100")

        if not (1 <= self.video_fps <= 120):
            raise ValueError(f"Invalid video_fps: {self.video_fps}. Must be between 1-120")

    def get_robot_cmd_address(self) -> str:
        """Get the full ZeroMQ address for robot command channel."""
        return f"tcp://{self.robot_host}:{self.robot_port_cmd}"

    def get_robot_data_address(self) -> str:
        """Get the full ZeroMQ address for robot data channel."""
        return f"tcp://{self.robot_host}:{self.robot_port_data}"

    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"ServerConfig(\n"
            f"  robot_type={self.robot_type}\n"
            f"  ui_server={self.ui_host}:{self.ui_port}\n"
            f"  robot_host={self.robot_host}:{self.robot_port_cmd}/{self.robot_port_data}\n"
            f"  video={self.video_width}x{self.video_height}@{self.video_fps}fps\n"
            f")"
        )