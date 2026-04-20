"""
Outland Agent - Docker Manager Service

Handles container lifecycle management, including:
- Dynamically spawn Redroid containers
- Container deletion (force delete)
- Port allocation (race condition protection)
- Container list query

Author: Outland Architecture Team
"""

import asyncio
import logging
import socket
import uuid
from dataclasses import dataclass
from typing import List, Optional

import docker
from docker.errors import DockerException, NotFound

logger = logging.getLogger(__name__)


@dataclass
class SpawnResult:
    """Container creation result"""
    container_id: str
    name: str
    host_port: int
    adb_port: int = 5555


class DockerManager:
    """
    Docker container manager
    
    Provides dynamic spawn and delete Redroid containers,
    supports port race condition protection.
    """
    
    # Redroid configuration constants
    # Note: Different image versions correspond to different Android versions
    # 11.0.0 -> Android 11 (SDK 30)
    # 12.0.0 -> Android 12 (SDK 31)
    # 13.0.0 -> Android 13 (SDK 33)
    REDROID_IMAGE = "redroid/redroid:13.0.0-latest"
    CONTAINER_PORT = 5555
    PORT_RANGE_START = 5555
    PORT_RANGE_END = 5600
    
    def __init__(self) -> None:
        """Initialize DockerManager"""
        self._client: Optional[docker.DockerClient] = None
        # Lock to prevent port allocation race conditions
        self._port_lock = asyncio.Lock()
        # Set of allocated ports (for tracking)
        self._allocated_ports: set = set()
    
    @property
    def client(self) -> docker.DockerClient:
        """Get Docker client (lazy loading)"""
        if self._client is None:
            self._client = docker.from_env()
            self._client.ping()
        return self._client
    
    def _is_port_available(self, port: int) -> bool:
        """
        Check if host port is available
        
        Args:
            port: Port number
            
        Returns:
            bool: Whether port is available
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("", port))
                return True
        except OSError:
            # Port is in use
            return False
    
    def _scan_available_port(self) -> Optional[int]:
        """
        Scan available ports in 5555-5600 range
        
        Returns:
            Optional[int]: Available port, None if no port found
        """
        for port in range(self.PORT_RANGE_START, self.PORT_RANGE_END + 1):
            # Check if port is already in allocated records
            if port in self._allocated_ports:
                continue
            # Check if port is actually available
            if self._is_port_available(port):
                return port
        return None
    
    def _check_port_in_use_by_containers(self) -> set:
        """
        Check ports occupied by current Docker containers
        
        Returns:
            set: Set of ports occupied by containers
        """
        allocated = set()
        try:
            containers = self.client.containers.list()
            for container in containers:
                ports = container.ports
                if ports:
                    for container_port_key in ports.keys():
                        # Format: "5555/tcp"
                        if "/" in container_port_key:
                            port_num = int(container_port_key.split("/")[0])
                            allocated.add(port_num)
        except DockerException as e:
            logger.warning("[DockerManager] Failed to get container list: %s", e)
        return allocated
    
    async def spawn_redroid(
        self,
        width: int = 720,
        height: int = 1280,
        fps: int = 30,
        device_model: str = "Outland_Cloud_Phone"
    ) -> SpawnResult:
        """
        Dynamically spawn a Redroid container
        
        Automatically finds available ports in range 5555-5600 on host,
        runs container in --privileged mode.
        
        Args:
            width: Screen width, default 720
            height: Screen height, default 1280
            fps: Framerate, default 30
            device_model: Device model, default "Outland_Cloud_Phone"
            
        Returns:
            SpawnResult: Contains container ID, name, and mapped port
            
        Raises:
            RuntimeError: Cannot find available port or container creation failed
        """
        # Use lock to prevent port allocation race condition
        async with self._port_lock:
            # Get allocated ports again (including container-occupied)
            container_ports = self._check_port_in_use_by_containers()
            self._allocated_ports.update(container_ports)
            
            # Scan available port
            port = self._scan_available_port()
            if port is None:
                raise RuntimeError(
                    f"Cannot find available port (range: {self.PORT_RANGE_START}-{self.PORT_RANGE_END}), "
                    f"currently allocated: {sorted(self._allocated_ports)}"
                )
            
            # Record allocation
            self._allocated_ports.add(port)
        
        # Generate container name (use redroid- prefix for list_instances to recognize correctly)
        container_name = f"redroid-{uuid.uuid4().hex[:8]}"
        
        # Build Redroid startup parameters (must include /init qemu=1 prefix)
        # /init is Redroid container's entry point, qemu=1 enables QEMU virtualization
        android_args = (
            f"/init qemu=1 "
            f"androidboot.redroid_width={width} "
            f"androidboot.redroid_height={height} "
            f"androidboot.redroid_fps={fps} "
            f"androidboot.redroid_device_model={device_model}"
        )
        
        logger.info(
            "[DockerManager] Spawning Redroid container: %s, port: %d, resolution: %dx%d@%dHz",
            container_name, port, width, height, fps
        )
        
        try:
            # Note: Don't use host network mode!
            # Host mode causes container to exit immediately (Exit 129)
            # Redroid needs its own network namespace
            container = self.client.containers.run(
                image=self.REDROID_IMAGE,
                detach=True,
                # Use privileged mode to ensure container has sufficient permissions
                privileged=True,
                name=container_name,
                command=android_args,
                # Port mapping: agent (host) accesses redroid ADB via localhost:port
                # Redroid container internal port 5555 maps to host port port
                ports={5555: port},
                # Use default bridge network mode (don't change to host!)
                # Host mode causes Redroid container to exit immediately
                # Increase shared memory to prevent Android system crash due to insufficient memory
                shm_size="2g",
                # Remove mem_limit, let Redroid use as much memory as possible
                # Note: Recommended host machine has at least 6GB available memory
                # mem_limit="4g",
                # Remove strict CPU limits, allow container to use all CPU resources
                # cpu_period=100000,
                # cpu_quota=200000,
                # Note: Don't add devices parameter to map ashmen/binder
                # These devices may not exist on host, --privileged is sufficient
                # Keep labels for identification
                labels={
                    "outland.service": "redroid",
                    "outland.version": "1.0.0"
                }
            )
            
            logger.info("[DockerManager] Container created successfully: %s (%s), port: %d", container.id, container_name, port)
            
            # Note: Use full container ID (64-bit), not short_id (12-bit) or name
            # Docker containers.get() support for short_id is unreliable in some cases
            # Full ID is the most reliable lookup method
            return SpawnResult(
                container_id=container.id,  # Use full ID, e.g., "a26884797f5b..."
                name=container_name,
                host_port=port,
                adb_port=self.CONTAINER_PORT
            )
            
        except DockerException as e:
            # Cleanup allocated port record
            self._allocated_ports.discard(port)
            raise RuntimeError(f"Container creation failed: {str(e)}") from e
    
    def delete_container(self, container_id: str, force: bool = True) -> bool:
        """
        Delete specified container
        
        Args:
            container_id: Container ID or name
            force: Whether to force delete (send SIGKILL), default True
            
        Returns:
            bool: Whether deletion was successful
            
        Raises:
            NotFound: Container not found
        """
        try:
            container = self.client.containers.get(container_id)
            container_name = container.name
            
            logger.info("[DockerManager] Deleting container: %s (force=%s)", container_name, force)
            container.remove(force=force)
            
            # Cleanup port record (simplified, actual can get port from container config)
            # Note: Since port may be reused by new container, don't auto-clean _allocated_ports here
            
            logger.info("[DockerManager] Container deleted successfully: %s", container_name)
            return True
            
        except NotFound:
            raise NotFound(f"Container {container_id} not found")
        except DockerException as e:
            raise RuntimeError(f"Container deletion failed: {str(e)}") from e
    
    def list_containers(self, running_only: bool = True) -> List[dict]:
        """
        Get Redroid container list
        
        Args:
            running_only: Whether to return only running containers, default True
            
        Returns:
            List[dict]: List of container info
        """
        try:
            all_containers = self.client.containers.list(all=not running_only)
            
            redroid_containers = []
            for container in all_containers:
                # Check if Redroid image
                image_tags = container.image.tags if container.image.tags else []
                if not any("redroid" in tag.lower() for tag in image_tags):
                    continue
                
                # Extract port mapping
                ports = []
                seen_ports = set()
                container_ports = container.ports or {}
                
                for container_port_key, host_bindings in container_ports.items():
                    if not host_bindings:
                        continue
                    for binding in host_bindings:
                        port_parts = container_port_key.split("/")
                        protocol = port_parts[1] if len(port_parts) > 1 else "tcp"
                        host_port = int(binding.get("HostPort", 0))
                        
                        port_key = (int(port_parts[0]), host_port, protocol)
                        if port_key in seen_ports:
                            continue
                        seen_ports.add(port_key)
                        
                        ports.append({
                            "container_port": port_key[0],
                            "host_port": port_key[1],
                            "protocol": port_key[2]
                        })
                
                redroid_containers.append({
                    # Note: Use full container ID, not short_id (12-bit)
                    # Docker containers.get() support for short_id is unreliable in some cases
                    "id": container.id,  # Full ID, e.g., "a26884797f5b..."
                    "name": container.name,
                    "status": container.status,
                    "state": container.attrs.get("State", {}).get("Status", "unknown"),
                    "image": image_tags[0] if image_tags else container.image.id,
                    "ports": ports,
                    "created_at": container.attrs.get("Created", "unknown")
                })
            
            return redroid_containers
            
        except DockerException as e:
            logger.error("[DockerManager] Failed to get container list: %s", e)
            return []
    
    def get_container_port(self, container_id: str) -> Optional[int]:
        """
        Get container's ADB port mapping
        
        Args:
            container_id: Container ID or name
            
        Returns:
            Optional[int]: Host port, None if no mapping found
        """
        try:
            container = self.client.containers.get(container_id)
            ports = container.ports
            port_key = "5555/tcp"
            
            if ports and port_key in ports:
                host_bindings = ports[port_key]
                if host_bindings and len(host_bindings) > 0:
                    return int(host_bindings[0]["HostPort"])
            
            # Default port (host network mode)
            return 5555
            
        except NotFound:
            return None
        except DockerException:
            return None

    async def resize_container(
        self,
        container_id: str,
        width: int = 720,
        height: int = 1280,
        fps: int = 30,
        device_model: str = "Outland_Cloud_Phone"
    ) -> SpawnResult:
        """
        Resize a Redroid container by recreating it with new resolution
        
        This operation will:
        1. Get current container info (port mapping, name)
        2. Stop and delete the old container
        3. Create a new container with new resolution but same port
        
        Args:
            container_id: Container ID or name
            width: New screen width, default 720
            height: New screen height, default 1280
            fps: New framerate, default 30
            device_model: Device model, default "Outland_Cloud_Phone"
            
        Returns:
            SpawnResult: Contains new container ID, name, and mapped port
            
        Raises:
            NotFound: Container not found
            RuntimeError: Port allocation or container creation failed
        """
        try:
            old_container = self.client.containers.get(container_id)
            old_container_name = old_container.name
            
            ports = old_container.ports
            port_key = "5555/tcp"
            port = 5555
            
            if ports and port_key in ports and ports[port_key]:
                port = int(ports[port_key][0]["HostPort"])
            
            logger.info(
                "[DockerManager] Resizing container %s to %dx%d@%dHz (port=%d)",
                old_container_name, width, height, fps, port
            )
            
            old_container.remove(force=True)
            logger.info("[DockerManager] Old container removed: %s", old_container_name)
            
        except NotFound:
            raise NotFound(f"Container {container_id} not found")
        except DockerException as e:
            raise RuntimeError(f"Failed to get container info: {str(e)}") from e
        
        self._allocated_ports.add(port)
        
        container_name = f"redroid-{uuid.uuid4().hex[:8]}"
        
        android_args = (
            f"/init qemu=1 "
            f"androidboot.redroid_width={width} "
            f"androidboot.redroid_height={height} "
            f"androidboot.redroid_fps={fps} "
            f"androidboot.redroid_device_model={device_model}"
        )
        
        logger.info(
            "[DockerManager] Creating resized container: %s, port: %d, resolution: %dx%d@%dHz",
            container_name, port, width, height, fps
        )
        
        try:
            container = self.client.containers.run(
                image=self.REDROID_IMAGE,
                detach=True,
                privileged=True,
                name=container_name,
                command=android_args,
                ports={5555: port},
                shm_size="2g",
                labels={
                    "outland.service": "redroid",
                    "outland.version": "1.0.0"
                }
            )
            
            logger.info("[DockerManager] Resized container created successfully: %s (%s), port: %d", container.id, container_name, port)
            
            return SpawnResult(
                container_id=container.id,
                name=container_name,
                host_port=port,
                adb_port=self.CONTAINER_PORT
            )
            
        except DockerException as e:
            self._allocated_ports.discard(port)
            raise RuntimeError(f"Container recreation failed: {str(e)}") from e


# ============================================================================
# Singleton Pattern for Global Access
# ============================================================================

_docker_manager: Optional[DockerManager] = None


def get_docker_manager() -> DockerManager:
    """
    Get global DockerManager instance (singleton pattern)
    
    Returns:
        DockerManager: Global manager instance
    """
    global _docker_manager
    if _docker_manager is None:
        _docker_manager = DockerManager()
    return _docker_manager
