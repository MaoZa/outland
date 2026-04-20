"""
Outland Agent Services

提供 ADB 控制、视频流捕获和 WebRTC 管理的核心模块。
"""

from services.adb_client import get_adb_manager, AdbManager
from services.webrtc_manager import get_webrtc_manager, shutdown_webrtc_manager

__all__ = [
    "get_adb_manager",
    "AdbManager",
    "get_webrtc_manager",
    "shutdown_webrtc_manager",
]
