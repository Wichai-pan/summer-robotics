"""
Core module for unified remote control system.

This module provides the core components for the simplified architecture:
- Configuration management
- Communication protocol definitions
- Remote control core implementation
"""

from .config import ServerConfig
from .protocol import RobotProtocol

__all__ = ['ServerConfig', 'RobotProtocol']