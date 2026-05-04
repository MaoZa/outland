"""
Outland Agent - ADB Client Manager

xProvides asynchronous ADB connection management with Redroid containers.
Uses adb-shell[async] library to control Android devices via TCP protocol.

Core Features (Simplified - Local Deployment):
- Singleton pattern: Global unique AdbManager instance
- Connection cache: Reuse ADB TCP connections to avoid repeated handshakes
- Simplified port discovery: Direct use of port 5555
"""

import asyncio
import collections
import json
import logging
import os
import re
import socket
import uuid
from typing import Dict, List, Optional

import docker
import httpx
from adb_shell.adb_device_async import AdbDeviceTcpAsync
from fastapi import HTTPException

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# ADB Server configuration (from environment variables)
ADB_SERVER_HOST: str = os.environ.get("ADB_SERVER_HOST", "127.0.0.1")
ADB_SERVER_PORT: int = int(os.environ.get("ADB_SERVER_PORT", "5037"))

# Redroid host address
# Priority: environment variable > localhost
# 
# Note: Agent is deployed on host machine (host network mode), redroid uses bridge network + port mapping
# Therefore Agent must access redroid via localhost:port
def _get_redroid_host() -> str:
    """Get Redroid host address"""
    # 1. Environment variable (highest priority, allows manual override)
    env_host = os.environ.get("REDROID_HOST")
    if env_host:
        return env_host
    # 2. Host deployment mode: Agent runs directly on the physical machine
    #    Redroid container uses bridge network + port mapping, Agent accesses via localhost
    if not os.path.exists("/.dockerenv"):
        return "localhost"
    # 3. Container deployment mode: Agent runs in Docker container
    return "host.docker.internal"

REDROID_HOST: str = _get_redroid_host()

# Redroid container's ADB service port
REDROID_ADB_PORT: int = int(os.environ.get("REDROID_ADB_PORT", "5555"))

# ADB connection timeout (seconds)
ADB_CONNECT_TIMEOUT: float = 10.0

# ADB shell execution timeout (seconds)
ADB_SHELL_TIMEOUT: float = 5.0


# ============================================================================
# ADB Device Exception Classes
# ============================================================================

class AdbOperationError(Exception):
    """ADB operation failure exception"""
    pass


class AdbConnectionError(Exception):
    """ADB connection failure exception"""
    pass


# ============================================================================
# AdbManager Singleton Class
# ============================================================================

class AdbManager:
    """
    ADB device manager (singleton pattern)
    
    Manages asynchronous ADB connections with all Android containers.
    Simplified: Direct connection to localhost:5555
    
    Attributes:
        _instance: Singleton instance
        _devices: Device connection cache dict, keyed by container_id
        _locks: Async lock dict for each container, prevents concurrent handshake collisions
        _screen_sizes: Cache of actual screen resolution for each container
    """
    
    _instance: Optional["AdbManager"] = None
    
    def __new__(cls) -> "AdbManager":
        """Ensure only one AdbManager instance globally"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """
        Initialize AdbManager
        """
        if self._initialized:
            return
        
        self._devices: Dict[str, AdbDeviceTcpAsync] = {}
        self._locks: Dict[str, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self._initialized = True
        # Cache actual screen resolution for each container
        self._screen_sizes: Dict[str, tuple[int, int]] = {}
        # External ADB address mapping: container_id -> "host:port"
        self._external_addresses: Dict[str, str] = {}
        # RSA key path mapping: container_id -> key file path
        self._rsa_key_paths: Dict[str, str] = {}
    
    # =========================================================================
    # Public API: Low-level action wrappers
    # =========================================================================
    
    async def tap(self, container_id: str, x: int, y: int) -> None:
        """
        Execute screen tap action
        
        Args:
            container_id: Docker container ID or name
            x: X coordinate of tap
            y: Y coordinate of tap
            
        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        await self._execute(container_id, f"input tap {x} {y}")
    
    async def swipe(
        self,
        container_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int = 300
    ) -> None:
        """
        Execute screen swipe action
        
        Args:
            container_id: Docker container ID or name
            x1: Start X coordinate
            y1: Start Y coordinate
            x2: End X coordinate
            y2: End Y coordinate
            duration: Swipe duration (milliseconds), default 300ms
            
        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        await self._execute(
            container_id,
            f"input swipe {x1} {y1} {x2} {y2} {duration}"
        )
    
    async def input_text(self, container_id: str, text: str) -> None:
        """
        Execute text input action
        
        Args:
            container_id: Docker container ID or name
            text: Text content to input
            
        Raises:
            HTTPException: Container not found or ADB connection failed
            
        Note:
            Text is strictly shell-escaped to prevent injection attacks.
            Single quotes are escaped as '\'' (single quote - backslash - single quote - single quote)
        """
        escaped = self._escape_shell_text(text)
        await self._execute(container_id, f"input text {escaped}")
    
    async def keyevent(self, container_id: str, keycode: int) -> None:
        """
        Execute key event
        
        Args:
            container_id: Docker container ID or name
            keycode: Android keycode (e.g., 26=POWER, 4=BACK, 3=HOME)
            
        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        await self._execute(container_id, f"input keyevent {keycode}")

    async def wake_screen(self, container_id: str) -> None:
        """
        Wake up screen and prevent it from sleeping during the session.

        Args:
            container_id: Docker container ID or name

        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        ext_addr = self._external_addresses.get(container_id)
        if ext_addr:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "adb", "connect", ext_addr,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=10)
            except Exception:
                pass
        await self._execute(container_id, "input keyevent 224")
        try:
            await self._execute(container_id, "svc power stayon true")
        except Exception:
            pass
        try:
            await self._execute(container_id, "settings put system screen_off_timeout 2147483647")
        except Exception:
            pass

    # =========================================================================
    # Screen resolution and coordinate conversion
    # =========================================================================

    def register_external_device(self, container_id: str, adb_address: str, rsa_key_path: Optional[str] = None) -> None:
        self._external_addresses[container_id] = adb_address
        if rsa_key_path:
            self._rsa_key_paths[container_id] = rsa_key_path
    
    def is_external_device(self, container_id: str) -> bool:
        return container_id in self._external_addresses or container_id.startswith("ext_")
    
    def get_external_address(self, container_id: str) -> Optional[str]:
        return self._external_addresses.get(container_id)
    
    def set_screen_size(self, container_id: str, width: int, height: int) -> None:
        """
        Set container screen resolution cache
        
        Performance optimization: Allows external (e.g., WebRTCManager) to pre-cache resolution,
        avoiding wm size command calls (~100-200ms overhead).
        
        Args:
            container_id: Docker container ID or name
            width: Screen width
            height: Screen height
        """
        self._screen_sizes[container_id] = (width, height)
        logger.debug("[AdbManager] Pre-cached screen resolution %s: %dx%d", container_id, width, height)
    
    async def get_screen_size(self, container_id: str) -> tuple[int, int]:
        """
        Get actual screen resolution of container
        
        Uses `wm size` command to get physical screen resolution.
        Results are cached for performance.
        
        Args:
            container_id: Docker container ID or name
            
        Returns:
            tuple[int, int]: (width, height)
        """
        # Check cache
        if container_id in self._screen_sizes:
            return self._screen_sizes[container_id]
        
        # Execute wm size command
        result = await self._execute(container_id, "wm size")
        
        # Parse output, e.g., "Physical size: 720x1280"
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", result)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
        else:
            # Default values
            width = 720
            height = 1280
        
        # Cache result
        self._screen_sizes[container_id] = (width, height)
        logger.info("[AdbManager] Screen resolution %s: %dx%d", container_id, width, height)
        return (width, height)
    
    async def _convert_coordinates(
        self,
        container_id: str,
        x: int,
        y: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> tuple[int, int]:
        """
        Convert Scrcpy video stream coordinates to actual screen coordinates

        Key handling (4 cases):
        - Portrait video + Portrait screen: no conversion needed (usually equal resolution)
        - Landscape video + Landscape screen: no conversion needed (usually equal resolution)
        - Landscape video + Portrait screen: swap axes (video rotated 90° for portrait screen)
        - Portrait video + Landscape screen: swap axes + coordinate flip (video rotated -90° for landscape screen)

        Args:
            container_id: Docker container ID or name
            x: X coordinate in Scrcpy video
            y: Y coordinate in Scrcpy video
            scrcpy_width: Scrcpy video width
            scrcpy_height: Scrcpy video height

        Returns:
            tuple[int, int]: (actual screen X, actual screen Y)
        """
        screen_width, screen_height = await self.get_screen_size(container_id)

        is_landscape_video = scrcpy_width > scrcpy_height
        is_landscape_screen = screen_width > screen_height

        logger.info(
            "[AdbManager] Coordinate conversion START %s: tap(%d,%d) video=%dx%d(%s) screen=%dx%d(%s)",
            container_id, x, y,
            scrcpy_width, scrcpy_height, "landscape" if is_landscape_video else "portrait",
            screen_width, screen_height, "landscape" if is_landscape_screen else "portrait"
        )

        # Case 1: Equal resolution - no conversion needed
        if screen_width == scrcpy_width and screen_height == scrcpy_height:
            logger.info(
                "[AdbManager] Case1-SAME: (%d,%d) -> (%d,%d) [no conversion needed]",
                x, y, x, y
            )
            return (x, y)

        # Case 2: Portrait video on Landscape screen (container rotated -90° to display portrait content)
        # Example: video=720x1280, screen=1280x720
        # Video top (videoY=0) appears at screen right edge after -90° rotation
        if not is_landscape_video and is_landscape_screen:
            # For -90° rotation:
            # - video's Y maps to screen's X (proportional)
            # - video's X maps to screen's Y (proportional)
            real_x = int(y * screen_width / scrcpy_height)
            real_y = int(x * screen_height / scrcpy_width)
            # Clamp to screen bounds
            real_x = max(0, min(real_x, screen_width - 1))
            real_y = max(0, min(real_y, screen_height - 1))

            logger.info(
                "[AdbManager] Case2-PORTRAIT_ON_LANDSCAPE: (%d,%d) @ %dx%d -> (%d,%d) @ %dx%d [rotation -90°]",
                x, y, scrcpy_width, scrcpy_height, real_x, real_y, screen_width, screen_height
            )
            return (real_x, real_y)

        # Case 3: Landscape video on Portrait screen (video rotated 90° to fit portrait screen)
        # Example: video=1280x720, screen=720x1280
        if is_landscape_video and not is_landscape_screen:
            real_x = int(y * screen_width / scrcpy_height)
            real_y = int(x * screen_height / scrcpy_width)
            real_x = max(0, min(real_x, screen_width - 1))
            real_y = max(0, min(real_y, screen_height - 1))

            logger.info(
                "[AdbManager] Case3-LANDSCAPE_ON_PORTRAIT: (%d,%d) @ %dx%d -> (%d,%d) @ %dx%d [rotation 90°]",
                x, y, scrcpy_width, scrcpy_height, real_x, real_y, screen_width, screen_height
            )
            return (real_x, real_y)

        # Case 4: Fallback - scale only (no rotation)
        # This handles cases where video and screen have same orientation but different sizes
        scale_x = screen_width / scrcpy_width
        scale_y = screen_height / scrcpy_height

        real_x = int(x * scale_x)
        real_y = int(y * scale_y)
        real_x = max(0, min(real_x, screen_width - 1))
        real_y = max(0, min(real_y, screen_height - 1))

        logger.info(
            "[AdbManager] Case4-SCALE_ONLY: (%d,%d) @ %dx%d -> (%d,%d) @ %dx%d [scale %.3f,%.3f]",
            x, y, scrcpy_width, scrcpy_height, real_x, real_y, screen_width, screen_height, scale_x, scale_y
        )

        return (real_x, real_y)
    
    async def tap_with_conversion(
        self,
        container_id: str,
        x: int,
        y: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> None:
        """
        Execute screen tap action (with coordinate conversion)
        
        Converts Scrcpy video stream coordinates to actual screen coordinates before tapping.
        
        Args:
            container_id: Docker container ID or name
            x: X coordinate in Scrcpy video
            y: Y coordinate in Scrcpy video
            scrcpy_width: Scrcpy video width
            scrcpy_height: Scrcpy video height

        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        real_x, real_y = await self._convert_coordinates(
            container_id, x, y, scrcpy_width, scrcpy_height
        )
        # Get screen size for logging
        sw, sh = await self.get_screen_size(container_id)
        logger.info(
            "[AdbManager] TAP: video(%d,%d) @ %dx%d -> screen(%d,%d) @ %dx%d | cmd: input tap %d %d",
            x, y, scrcpy_width, scrcpy_height, real_x, real_y, sw, sh, real_x, real_y
        )
        await self._execute(container_id, f"input tap {real_x} {real_y}")
    
    async def swipe_with_conversion(
        self,
        container_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> None:
        """
        Execute screen swipe action (with coordinate conversion)
        
        Converts Scrcpy video stream coordinates to actual screen coordinates before swiping.
        
        Args:
            container_id: Docker container ID or name
            x1: Start X coordinate (Scrcpy video coordinates)
            y1: Start Y coordinate (Scrcpy video coordinates)
            x2: End X coordinate (Scrcpy video coordinates)
            y2: End Y coordinate (Scrcpy video coordinates)
            duration: Swipe duration (milliseconds)
            scrcpy_width: Scrcpy video width
            scrcpy_height: Scrcpy video height
            
        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        real_x1, real_y1 = await self._convert_coordinates(
            container_id, x1, y1, scrcpy_width, scrcpy_height
        )
        real_x2, real_y2 = await self._convert_coordinates(
            container_id, x2, y2, scrcpy_width, scrcpy_height
        )
        logger.info(
            "[AdbManager] SWIPE: video(%d,%d)->(%d,%d) @ %dx%d -> screen(%d,%d)->(%d,%d) | cmd: input swipe %d %d %d %d %d",
            x1, y1, x2, y2, scrcpy_width, scrcpy_height, real_x1, real_y1, real_x2, real_y2, real_x1, real_y1, real_x2, real_y2, duration
        )
        await self._execute(
            container_id,
            f"input swipe {real_x1} {real_y1} {real_x2} {real_y2} {duration}"
        )
    
    async def long_press(
        self,
        container_id: str,
        x: int,
        y: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> None:
        """
        Execute screen long press action (with coordinate conversion)
        
        Android ADB has no direct long_press command, use input swipe to simulate:
        Swipe with same start and end point for 1000ms (1 second) to simulate long press.
        
        Args:
            container_id: Docker container ID or name
            x: X coordinate (Scrcpy video coordinates)
            y: Y coordinate (Scrcpy video coordinates)
            scrcpy_width: Scrcpy video width
            scrcpy_height: Scrcpy video height
            
        Raises:
            HTTPException: Container not found or ADB connection failed
        """
        real_x, real_y = await self._convert_coordinates(
            container_id, x, y, scrcpy_width, scrcpy_height
        )
        # Long press duration 1000ms (1 second)
        await self._execute(
            container_id,
            f"input swipe {real_x} {real_y} {real_x} {real_y} 1000"
        )
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    async def _get_or_connect(self, container_id: str) -> AdbDeviceTcpAsync:
        """
        Get or create ADB device connection
        
        Args:
            container_id: Docker container ID or name
            
        Returns:
            AdbDeviceTcpAsync: ADB device object
            
        Raises:
            HTTPException: Container not found or connection failed
        """
        # If cached connection exists, return directly
        if container_id in self._devices:
            return self._devices[container_id]
        
        # Use container-level lock to prevent concurrent handshake collisions
        async with self._locks[container_id]:
            # Double check: after acquiring lock, confirm connection again
            if container_id in self._devices:
                return self._devices[container_id]
            
            # Establish new connection
            await self._connect_device(container_id)
            return self._devices[container_id]
    
    async def _connect_device(self, container_id: str) -> None:
        """
        Establish ADB TCP connection with specified container
        
        Args:
            container_id: Docker container ID or name
            
        Raises:
            HTTPException: Container not found or connection failed
        """
        try:
            ext_addr = self._external_addresses.get(container_id)
            if ext_addr:
                host, _, port_str = ext_addr.partition(":")
                port = int(port_str) if port_str else 5555
                logger.info("[AdbManager] Connecting to external device %s at %s:%d", container_id, host, port)
                device = AdbDeviceTcpAsync(host, port)
                await device.connect()
                self._devices[container_id] = device
                return

            host_port = self._get_container_adb_port(container_id)
            target_host = self._resolve_host(REDROID_HOST)
            device = AdbDeviceTcpAsync(target_host, host_port)
            await device.connect()
            self._devices[container_id] = device
            
        except docker.errors.NotFound:
            raise HTTPException(
                status_code=404,
                detail=f"Container {container_id} not found"
            )
        except socket.timeout:
            raise HTTPException(
                status_code=504,
                detail=f"ADB connection timeout: container {container_id}'s {REDROID_ADB_PORT}/tcp port not responding"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"ADB connection failed: {str(e)}"
            )
    
    def _get_container_adb_port(self, container_id: str) -> int:
        ext_addr = self._external_addresses.get(container_id)
        if ext_addr:
            _, _, port_str = ext_addr.partition(":")
            return int(port_str) if port_str else 5555

        if container_id in ("localhost", "default", "redroid"):
            logger.info("[AdbManager] Using direct ADB connection identifier '%s', returning port %d", container_id, REDROID_ADB_PORT)
            return REDROID_ADB_PORT
        
        try:
            # First check if Docker socket exists
            docker_socket = "/var/run/docker.sock"
            if not os.path.exists(docker_socket):
                # Docker socket not found (host network mode), return default port
                logger.info("[AdbManager] Docker socket not found, using host network mode, returning %d", REDROID_ADB_PORT)
                return REDROID_ADB_PORT
            
            client = docker.from_env()
            container = client.containers.get(container_id)
            
            ports = container.ports
            container_port_str = f"{REDROID_ADB_PORT}/tcp"
            
            if ports and container_port_str in ports:
                host_bindings = ports[container_port_str]
                if host_bindings and len(host_bindings) > 0:
                    host_port = int(host_bindings[0]["HostPort"])
                    logger.info("[AdbManager] Container '%s' ADB port mapping: %d -> %d", container_id, REDROID_ADB_PORT, host_port)
                    return host_port
            
            # If no port mapping (host network mode), return 5555 directly
            logger.info("[AdbManager] Container '%s' has no port mapping, using host network mode, returning %d", container_id, REDROID_ADB_PORT)
            return REDROID_ADB_PORT
            
        except FileNotFoundError:
            # Docker socket not found, assume host network mode
            logger.info("[AdbManager] Docker socket not found, using host network mode, returning %d", REDROID_ADB_PORT)
            return REDROID_ADB_PORT
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Container {container_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            # If Docker connection error, assume host network mode
            if "docker" in str(e).lower() or "socket" in str(e).lower():
                logger.info("[AdbManager] Docker connection failed (%s), using host network mode, returning %d", str(e), REDROID_ADB_PORT)
                return REDROID_ADB_PORT
            raise HTTPException(status_code=500, detail=f"Failed to get container port mapping: {str(e)}")
    
    async def _execute(self, container_id: str, command: str) -> str:
        """
        Execute ADB shell command on specified container
        
        For external devices (MIUI etc.) that require TLS, use adb CLI instead
        of adb_shell library which doesn't support ADB TLS authentication.
        """
        ext_addr = self._external_addresses.get(container_id)
        if ext_addr:
            return await self._execute_via_cli(ext_addr, command)

        device = await self._get_or_connect(container_id)
        
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(
                    device.shell(command),
                    timeout=ADB_SHELL_TIMEOUT
                )
                if isinstance(result, bytes):
                    return result.decode("utf-8", errors="replace")
                elif isinstance(result, str):
                    return result
                else:
                    return str(result) if result else ""
                
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=504,
                    detail=f"ADB Shell execution timeout: {command}"
                )
            except (socket.error, ConnectionResetError, ConnectionRefusedError) as e:
                self._devices.pop(container_id, None)
                if attempt == 0:
                    continue
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"ADB connection dropped and cannot be rebuilt: {str(e)}"
                    )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"ADB Shell execution failed: {str(e)}"
                )
        
        raise HTTPException(
            status_code=500,
            detail="ADB execution exception: unknown error"
        )
    
    async def _execute_via_cli(self, device_address: str, command: str) -> str:
        """
        Execute ADB shell command via adb CLI for external devices.
        
        External devices (MIUI wireless debugging) require TLS authentication
        which the adb_shell library doesn't support. The adb CLI handles TLS
        natively since it's already connected via 'adb connect'.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", device_address, "shell", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=ADB_SHELL_TIMEOUT
            )
            if proc.returncode != 0:
                err = stderr_bytes.decode("utf-8", errors="replace").strip()
                raise HTTPException(
                    status_code=500,
                    detail=f"ADB shell failed (code {proc.returncode}): {err}"
                )
            return stdout_bytes.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"ADB Shell execution timeout (via CLI): {command}"
            )
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    @staticmethod
    def _resolve_host(host: str) -> str:
        """
        Resolve hostname to IP address
        
        DNS resolution error [Errno -3] usually occurs in Docker container environments,
        when using hostname (e.g., localhost) that cannot be resolved correctly.
        This method resolves common hostnames to corresponding IP addresses.
        
        Args:
            host: Original hostname (may need resolution)
            
        Returns:
            str: Directly usable IP address or hostname
        """
        # If already an IP address, return directly
        if host.replace(".", "").isdigit():
            return host
        
        # Special handling for common hostnames
        host_lower = host.lower()
        
        # localhost / 127.0.0.1
        if host_lower in ("localhost", "localhost.localdomain", "host.docker.internal"):
            logger.info("[AdbManager] Resolved hostname '%s' -> 127.0.0.1", host)
            return "127.0.0.1"
        
        # Try DNS resolution
        try:
            result = socket.gethostbyname(host)
            logger.info("[AdbManager] DNS resolved '%s' -> %s", host, result)
            return result
        except socket.gaierror as e:
            # DNS resolution failed, fallback to original value
            logger.warning("[AdbManager] DNS resolution '%s' failed: %s, using original value", host, e)
            return host
    
    @staticmethod
    def _escape_shell_text(text: str) -> str:
        """
        Escape text to safe shell string
        
        Uses single-quote wrapping + internal single-quote escaping.
        Example: I'm Bot -> 'I'\\''m Bot'
        
        Args:
            text: Original text
            
        Returns:
            str: Escaped safe string
        """
        # Escape internal single quotes as '\'' (single quote - backslash - single quote - single quote)
        escaped = text.replace("'", "'\\''")
        return f"'{escaped}'"
    
    async def close(self, container_id: str) -> None:
        """
        Close ADB connection for specified container
        
        Args:
            container_id: Docker container ID or name
        """
        if container_id in self._devices:
            try:
                await self._devices[container_id].close()
            except Exception:
                pass
            finally:
                self._devices.pop(container_id, None)
    
    async def close_all(self) -> None:
        """Close all ADB connections"""
        for container_id in list(self._devices.keys()):
            await self.close(container_id)
    
    # =========================================================================
    # APK Installation (Async Version)
    # =========================================================================
    
    async def _run_adb_command(self, args: list[str], timeout: float = 120.0) -> tuple[int, str, str]:
        """
        Run ADB command (async version)
        
        Args:
            args: adb command argument list
            timeout: Timeout (seconds)
            
        Returns:
            tuple[int, str, str]: (returncode, stdout, stderr)
        """
        proc = await asyncio.create_subprocess_exec(
            "adb", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, stdout_bytes.decode("utf-8", errors="replace"), stderr_bytes.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise asyncio.TimeoutError(f"ADB command timeout ({timeout}s): adb {' '.join(args)}")
    
    async def install_apk(self, container_id: str, apk_path: str) -> dict:
        """
        Install APK file to specified container (async version)
        
        Args:
            container_id: Docker container ID or name
            apk_path: Absolute path to APK file
            
        Returns:
            dict: Dictionary containing success and message
            
        Raises:
            AdbOperationError: Installation failed
        """
        logger.info("[APK Install] Starting APK installation: %s to container %s", apk_path, container_id)
        
        # Verify APK file exists
        if not os.path.exists(apk_path):
            raise AdbOperationError(f"APK file not found: {apk_path}")
        
        # Verify file size (APK usually larger than 1KB)
        file_size = os.path.getsize(apk_path)
        if file_size < 1024:
            raise AdbOperationError(f"File too small, not a valid APK: {apk_path} ({file_size} bytes)")
        
        try:
            # Dynamically get container's ADB port
            adb_port = self._get_container_adb_port(container_id)
            
            # Step 1 - Connect device
            returncode, stdout, stderr = await self._run_adb_command(
                ["connect", f"localhost:{adb_port}"], timeout=10
            )
            logger.info("[APK Install] connect stdout: %s", stdout)
            if stderr:
                logger.info("[APK Install] connect stderr: %s", stderr)
            
            # Step 2 - Install APK (-r: replace existing app, -g: grant all runtime permissions)
            returncode, stdout, stderr = await self._run_adb_command(
                ["-s", f"localhost:{adb_port}", "install", "-r", "-g", apk_path], timeout=180
            )
            logger.info("[APK Install] install stdout: %s", stdout)
            if stderr:
                logger.info("[APK Install] install stderr: %s", stderr)
            
            # Check installation result
            if returncode == 0 and "Success" in stdout:
                logger.info("[APK Install] APK installation successful")
                return {
                    "success": True,
                    "message": f"APK installation successful: {stdout.strip()}"
                }
            else:
                error_msg = f"Installation failed: returncode={returncode}"
                if stdout:
                    error_msg += f", stdout={stdout}"
                if stderr:
                    error_msg += f", stderr={stderr}"
                logger.error("[APK Install] %s", error_msg)
                raise AdbOperationError(error_msg)
                
        except asyncio.TimeoutError as e:
            logger.error("[APK Install] %s", e)
            raise AdbOperationError(str(e))
        except AdbOperationError:
            raise
        except Exception as e:
            error_msg = f"APK installation failed: {e}"
            logger.error("[APK Install] %s", error_msg)
            raise AdbOperationError(error_msg)

    async def install_xapk(self, container_id: str, xapk_path: str) -> dict:
        """
        Install XAPK file to specified container.

        XAPK is ZIP format, containing one base APK and multiple split APKs.
        Some apps (e.g., Chrome) need to install shared library before main app.

        Installation strategies (in order):
        1. Install shared libs first, then base+split APKs
        2. Install all APKs together
        3. Install non-shared APKs first, then shared libs

        Args:
            container_id: Docker container ID or name
            xapk_path: Absolute path to XAPK file

        Returns:
            dict: Dictionary containing success and message

        Raises:
            AdbOperationError: Installation failed
        """
        import zipfile
        import tempfile
        import shutil

        logger.info("[XAPK Install] Starting XAPK installation: %s to container %s", xapk_path, container_id)

        temp_dir = None
        try:
            self._validate_xapk(xapk_path)
            temp_dir, apk_files, main_package = self._extract_xapk(xapk_path)
            shared_libs, base_apk, split_apks = self._classify_apks(apk_files, main_package)

            adb_port = self._get_container_adb_port(container_id)
            target = f"localhost:{adb_port}"

            await self._run_adb_command(["connect", target], timeout=10)

            if shared_libs:
                result = await self._try_strategy_with_shared_libs(target, shared_libs, base_apk, split_apks, len(apk_files))
                if result:
                    return result

            result = await self._try_strategy_all_together(target, apk_files, len(apk_files))
            if result:
                return result

            if shared_libs:
                result = await self._try_strategy_non_libs_first(target, shared_libs, base_apk, split_apks, len(apk_files))
                if result:
                    return result

            raise AdbOperationError("XAPK installation failed after all strategies")

        except AdbOperationError:
            raise
        except Exception as e:
            raise AdbOperationError(f"XAPK installation failed: {e}")
        finally:
            if temp_dir:
                self._cleanup_temp_dir(temp_dir)

    def _validate_xapk(self, xapk_path: str) -> None:
        """Validate XAPK file before extraction."""
        if not os.path.exists(xapk_path):
            raise AdbOperationError(f"XAPK file not found: {xapk_path}")

        file_size = os.path.getsize(xapk_path)
        if file_size < 1024:
            raise AdbOperationError(f"File too small, not a valid XAPK: {xapk_path} ({file_size} bytes)")

        if not zipfile.is_zipfile(xapk_path):
            raise AdbOperationError(f"File is not valid ZIP format: {xapk_path}")

    def _extract_xapk(self, xapk_path: str) -> tuple:
        """
        Extract XAPK and collect APK files and main package name.

        Returns:
            tuple: (temp_dir, apk_files list, main_package string)
        """
        import zipfile
        import tempfile

        temp_dir = tempfile.mkdtemp(prefix="outland_xapk_")
        logger.info("[XAPK Install] Extracting to temp directory: %s", temp_dir)

        with zipfile.ZipFile(xapk_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        apk_files: List[str] = []
        main_package: str = ""

        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(".apk") and not file.endswith(".apk.orig"):
                    apk_files.append(os.path.join(root, file))
                elif file == "manifest.json":
                    manifest_path = os.path.join(root, file)
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest_data = json.load(f)
                        if isinstance(manifest_data, dict):
                            main_package = manifest_data.get("package_name", "")
                        logger.info("[XAPK Install] Parsed manifest.json, main package: %s", main_package)
                    except Exception as e:
                        logger.warning("[XAPK Install] Failed to parse manifest.json: %s", e)

        if not apk_files:
            raise AdbOperationError(f"No APK files found in XAPK: {xapk_path}")

        logger.info("[XAPK Install] Found %d APK files", len(apk_files))
        for apk in apk_files:
            logger.info("[XAPK Install]   - %s", os.path.basename(apk))

        return temp_dir, apk_files, main_package

    def _classify_apks(self, apk_files: List[str], main_package: str) -> tuple:
        """
        Classify APK files into shared_libs, base_apk, and split_apks.

        Returns:
            tuple: (shared_libs list, base_apk string or None, split_apks list)
        """
        shared_libs: List[str] = []
        base_apk: Optional[str] = None
        split_apks: List[str] = []
        main_pkg_short = main_package.split(".")[-1] if main_package else ""

        for apk in apk_files:
            apk_name = os.path.basename(apk)
            apk_stem = apk_name.rsplit(".", 1)[0]

            is_shared_lib = (
                ("." in apk_stem or apk_name.startswith("com.") or apk_name.startswith("org.") or apk_name.startswith("android"))
                and (main_pkg_short and apk_stem != main_pkg_short)
            )

            if is_shared_lib:
                shared_libs.append(apk)
                logger.info("[XAPK Install] Identified as shared library: %s", apk_name)
            elif main_pkg_short and (apk_stem == main_pkg_short or apk_stem == main_package.replace(".", "_")):
                base_apk = apk
                logger.info("[XAPK Install] Identified as base APK: %s", apk_name)
            else:
                if main_package and apk_stem in main_package:
                    base_apk = apk
                    logger.info("[XAPK Install] Identified as base APK (fuzzy match): %s", apk_name)
                else:
                    split_apks.append(apk)
                    logger.info("[XAPK Install] Identified as split APK: %s", apk_name)

        if not base_apk and len(apk_files) > 0:
            largest_apk = max(apk_files, key=lambda f: os.path.getsize(f))
            if not any(largest_apk == lib for lib in shared_libs):
                base_apk = largest_apk
                logger.info("[XAPK Install] Identified as base APK (largest file): %s", os.path.basename(largest_apk))

        logger.info("[XAPK Install] Classification: shared_libs=%d, base_apk=%s, split_apks=%d",
                     len(shared_libs), os.path.basename(base_apk) if base_apk else "None", len(split_apks))

        return shared_libs, base_apk, split_apks

    async def _install_shared_libraries(self, target: str, shared_libs: List[str]) -> None:
        """Install shared library APKs one by one."""
        for lib_apk in shared_libs:
            lib_name = os.path.basename(lib_apk)
            logger.info("[XAPK Install] Installing shared library: %s", lib_name)
            returncode, stdout, stderr = await self._run_adb_command(
                ["-s", target, "install", "-r", "-g", lib_apk], timeout=120
            )
            if returncode == 0:
                logger.info("[XAPK Install] Shared library installed successfully: %s", lib_name)
            else:
                logger.warning("[XAPK Install] Shared library installation failed, continuing: %s, stderr: %s", lib_name, stderr)

    async def _install_apk_list(self, target: str, apk_list: List[str], description: str) -> tuple:
        """
        Install a list of APKs using install-multiple.

        Returns:
            tuple: (returncode, stdout, stderr)
        """
        if not apk_list:
            return 0, "", ""

        cmd_args = ["-s", target, "install-multiple", "-r", "-g"] + apk_list
        logger.info("[XAPK Install] %s with install-multiple...", description)
        returncode, stdout, stderr = await self._run_adb_command(cmd_args, timeout=300)
        logger.info("[XAPK Install] stdout: %s", stdout)
        if stderr:
            logger.info("[XAPK Install] stderr: %s", stderr)
        return returncode, stdout, stderr

    async def _try_strategy_with_shared_libs(self, target: str, shared_libs: List[str], base_apk: Optional[str], split_apks: List[str], total_apks: int) -> Optional[dict]:
        """Strategy 1: Install shared libs first, then base+split APKs."""
        logger.info("[XAPK Install] Trying strategy 1: shared libs first...")

        await self._install_shared_libraries(target, shared_libs)

        remaining_apks = ([base_apk] if base_apk else []) + split_apks
        if remaining_apks:
            returncode, stdout, stderr = await self._install_apk_list(target, remaining_apks, "Installing base+split APKs")
            if returncode == 0 and "Success" in stdout:
                logger.info("[XAPK Install] XAPK installation successful")
                return {"success": True, "message": f"XAPK installation successful, contains {total_apks} APKs"}

        logger.warning("[XAPK Install] Strategy 1 failed, trying strategy 2...")
        return None

    async def _try_strategy_all_together(self, target: str, apk_files: List[str], total_apks: int) -> Optional[dict]:
        """Strategy 2: Install all APKs together."""
        logger.info("[XAPK Install] Trying strategy 2: all together...")

        returncode, stdout, stderr = await self._install_apk_list(target, apk_files, "Installing all APKs")
        if returncode == 0 and "Success" in stdout:
            logger.info("[XAPK Install] XAPK installation successful")
            return {"success": True, "message": f"XAPK installation successful, contains {total_apks} APKs"}

        return None

    async def _try_strategy_non_libs_first(self, target: str, shared_libs: List[str], base_apk: Optional[str], split_apks: List[str], total_apks: int) -> Optional[dict]:
        """Strategy 3: Install non-shared-libs first, then shared libs."""
        logger.info("[XAPK Install] Trying strategy 3: non-shared-libs first...")

        non_lib_apks = ([base_apk] if base_apk else []) + split_apks
        if not non_lib_apks:
            return None

        returncode, stdout, stderr = await self._install_apk_list(target, non_lib_apks, "Installing non-shared-lib APKs")
        if returncode == 0 or "Success" in stdout:
            logger.info("[XAPK Install] Non-shared-lib APKs installed, now trying with shared libs")
            returncode, stdout, stderr = await self._install_apk_list(target, shared_libs, "Installing shared libs")
            if returncode == 0 and "Success" in stdout:
                logger.info("[XAPK Install] XAPK installation successful (strategy 3)")
                return {"success": True, "message": f"XAPK installation successful, contains {total_apks} APKs"}

        return None

    def _cleanup_temp_dir(self, temp_dir: str) -> None:
        """Clean up temporary directory."""
        import shutil
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info("[XAPK Install] Cleaned up temp directory: %s", temp_dir)
            except Exception:
                pass


# ============================================================================
# Singleton accessor function
# ============================================================================

_adb_manager: Optional["AdbManager"] = None

def get_adb_manager() -> AdbManager:
    """
    Get global AdbManager instance (singleton)
    
    Returns:
        AdbManager: Global manager instance
    """
    global _adb_manager
    if _adb_manager is None:
        _adb_manager = AdbManager()
    return _adb_manager
