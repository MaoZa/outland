"""
Outland Agent - Main Application Entry Point

Lightweight FastAPI application deployed on the physical machine running Redroid.
Provides WebRTC streaming, ADB control, and container management.

Core Endpoints:
- GET  /health                    → Health check
- POST /api/stream/webrtc/offer   → WebRTC handshake
- POST /api/action/click          → ADB tap
- POST /api/action/swipe         → ADB swipe
- POST /api/action/text          → ADB text input
- POST /api/action/keyevent       → ADB key event
- GET  /api/instances             → Container list
- GET  /api/container/{id}/adb_port → Get container ADB port

Agent Registry Features:
- Auto-register with Backend on startup
- Send heartbeat every 30 seconds
"""

import asyncio
import logging
import os
import socket
import uuid
import docker
from contextlib import asynccontextmanager
from typing import Annotated, List, Optional

# Configure global logging to ensure ScrcpyTrack / WebRTC module logs output properly
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Reduce noise from third-party libraries
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.INFO)
logging.getLogger("av").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("docker.utils").setLevel(logging.WARNING)

# Create logger instance
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.docker_manager import get_docker_manager, SpawnResult
from services.webrtc_manager import shutdown_webrtc_manager


# ============================================================================
# Agent Configuration
# ============================================================================

# Backend connection configuration
BACKEND_URL: str = os.environ.get("BACKEND_URL", "http://localhost:8000")
AGENT_ADVERTISED_URL: Optional[str] = os.environ.get("AGENT_ADVERTISED_URL")
HEARTBEAT_INTERVAL = 30  # Heartbeat interval (seconds)

# Agent unique identifier
AGENT_ID: str = os.environ.get("AGENT_ID") or socket.gethostname() or uuid.uuid4().hex[:8]


def get_local_ip() -> str:
    """
    Get local IP address.
    
    Determines local IP by creating a UDP socket connection to an external DNS.
    This is a common method to get local LAN IP.
    """
    try:
        # Create UDP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        # Connect to external address (no actual data sent)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_agent_url() -> str:
    """
    Get Agent access URL.
    
    Prefers environment variable AGENT_ADVERTISED_URL,
    otherwise auto-detects local IP:9090.
    """
    if AGENT_ADVERTISED_URL:
        return AGENT_ADVERTISED_URL
    local_ip = get_local_ip()
    return f"http://{local_ip}:9090"


# ============================================================================
# Pydantic Models
# ============================================================================

class PortMapping(BaseModel):
    """Port mapping model"""
    container_port: int
    host_port: int
    protocol: str = "tcp"


class ContainerInfo(BaseModel):
    """Container info model"""
    name: str
    id: str
    status: str
    state: str
    image: str
    ports: List[PortMapping]
    created_at: str


class InstanceListResponse(BaseModel):
    """Instance list response model"""
    total: int
    instances: List[ContainerInfo]


# ============================================================================
# WebRTC Models
# ============================================================================

class WebRTCOfferRequest(BaseModel):
    """WebRTC Offer request model"""
    container_id: str
    sdp: str
    type: str = "offer"


class WebRTCAnswerResponse(BaseModel):
    """WebRTC Answer response model"""
    sdp: str
    type: str


# ============================================================================
# Action Models
# ============================================================================

class ClickRequest(BaseModel):
    """Click action request model"""
    container_id: Annotated[str, Field(description="Docker container ID or name", min_length=1)]
    x: Annotated[int, Field(description="X coordinate of tap", ge=0)]
    y: Annotated[int, Field(description="Y coordinate of tap", ge=0)]


class SwipeRequest(BaseModel):
    """Swipe action request model"""
    container_id: Annotated[str, Field(description="Docker container ID or name", min_length=1)]
    x1: Annotated[int, Field(description="Start X coordinate", ge=0)]
    y1: Annotated[int, Field(description="Start Y coordinate", ge=0)]
    x2: Annotated[int, Field(description="End X coordinate", ge=0)]
    y2: Annotated[int, Field(description="End Y coordinate", ge=0)]
    duration: Annotated[int, Field(description="Swipe duration (milliseconds)", ge=0, default=300)]


class TextRequest(BaseModel):
    """Text input request model"""
    container_id: Annotated[str, Field(description="Docker container ID or name", min_length=1)]
    text: Annotated[str, Field(description="Text content to input")]


class KeyEventRequest(BaseModel):
    """Key event request model"""
    container_id: Annotated[str, Field(description="Docker container ID or name", min_length=1)]
    keycode: Annotated[int, Field(description="Android keycode (e.g., 26=POWER, 4=BACK, 3=HOME)")]


class ActionResponse(BaseModel):
    """Action success response model"""
    success: bool = True
    container_id: str
    action: str
    detail: str = ""


# ============================================================================
# Container Spawn Models
# ============================================================================

class SpawnRequest(BaseModel):
    """
    Container creation request model
    
    Supports custom resolution, framerate, and device model for Redroid containers.
    """
    width: Annotated[int, Field(description="Screen width (pixels)", ge=320, le=3840, default=720)] = 720
    height: Annotated[int, Field(description="Screen height (pixels)", ge=480, le=2160, default=1280)] = 1280
    fps: Annotated[int, Field(description="Framerate", ge=1, le=60, default=30)] = 30
    device_model: Annotated[str, Field(description="Device model", default="Outland_Cloud_Phone")] = "Outland_Cloud_Phone"


class SpawnResponse(BaseModel):
    """Container creation response model"""
    success: bool = True
    container_id: str
    name: str
    host_port: int
    adb_port: int = 5555
    message: str = ""


class ResizeRequest(BaseModel):
    """
    Container resize request model
    
    Same as SpawnRequest but for resizing existing containers.
    """
    width: Annotated[int, Field(description="Screen width (pixels)", ge=320, le=3840, default=720)] = 720
    height: Annotated[int, Field(description="Screen height (pixels)", ge=480, le=2160, default=1280)] = 1280
    fps: Annotated[int, Field(description="Framerate", ge=1, le=60, default=30)] = 30
    device_model: Annotated[str, Field(description="Device model", default="Outland_Cloud_Phone")] = "Outland_Cloud_Phone"


# ============================================================================
# Agent Registry Background Tasks
# ============================================================================

async def _heartbeat_loop():
    """
    Background heartbeat loop task.
    
    Sends registration/heartbeat requests to Backend every HEARTBEAT_INTERVAL seconds.
    Sends registration request on first startup, then only heartbeats.
    """
    import httpx
    
    agent_url = get_agent_url()
    registered = False
    
    print(f"[Outland Agent] Heartbeat loop started, Backend: {BACKEND_URL}, Agent URL: {agent_url}")
    
    while True:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if not registered:
                    # First: send registration request
                    print(f"[Outland Agent] Registering to Backend: {BACKEND_URL}")
                    resp = await client.post(
                        f"{BACKEND_URL}/api/agents/register",
                        json={
                            "agent_id": AGENT_ID,
                            "url": agent_url
                        }
                    )
                    resp.raise_for_status()
                    print(f"[Outland Agent] Registered to Backend successfully")
                    registered = True
                else:
                    # Subsequent: send heartbeat
                    resp = await client.post(
                        f"{BACKEND_URL}/api/agents/heartbeat",
                        json={"agent_id": AGENT_ID}
                    )
                    resp.raise_for_status()
                    
        except httpx.HTTPStatusError as e:
            print(f"[Outland Agent] Backend error: {e.response.status_code} - {e.response.text}")
            # If 404, not registered, reset state
            if e.response.status_code == 404:
                registered = False
        except Exception as e:
            print(f"[Outland Agent] Heartbeat error: {e}")
            # Reset registration state on connection failure, re-register next cycle
            registered = False
        
        await asyncio.sleep(HEARTBEAT_INTERVAL)


# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    # Startup
    print("[Outland Agent] Starting up...")
    print(f"[Outland Agent] Agent ID: {AGENT_ID}")
    print(f"[Outland Agent] Backend URL: {BACKEND_URL}")
    print(f"[Outland Agent] Advertised URL: {get_agent_url()}")
    
    # Start background heartbeat task
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    
    # Note: In the new architecture, Redroid containers are created on-demand
    # App initialization (Nova Launcher, Aurora Store, TapTap) should be done via API after container creation
    # No longer trying to connect to non-existent containers on startup
    
    yield
    
    # Shutdown: cleanup WebRTC and ADB resources
    print("[Outland Agent] Shutting down...")
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await shutdown_webrtc_manager()


app = FastAPI(
    title="Outland Agent",
    description="Remote Android cloud container proxy, provides WebRTC streaming and ADB control services",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production should restrict to specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Docker Client Helper
# ============================================================================

def get_docker_client() -> docker.DockerClient:
    """
    Get Docker client instance.
    
    Returns:
        docker.DockerClient: Docker client
        
    Raises:
        HTTPException: Docker connection failure
    """
    try:
        client = docker.from_env()
        client.ping()
        return client
    except docker.errors.DockerException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Docker service not started or cannot connect: {str(e)}"
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Docker operation permissions, ensure user has docker group: {str(e)}"
        )


# ============================================================================
# API Routes: Health
# ============================================================================

@app.get("/", tags=["Health"])
async def root():
    """Service root path"""
    return {"status": "ok", "service": "outland-agent", "agent_id": AGENT_ID}


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check (includes Docker status)"""
    try:
        client = get_docker_client()
        docker_info = client.info()
        return {
            "status": "healthy",
            "docker": "connected",
            "docker_version": docker_info.get("ServerVersion", "unknown"),
            "agent_id": AGENT_ID
        }
    except HTTPException:
        return {
            "status": "degraded",
            "docker": "disconnected"
        }


# ============================================================================
# API Routes: Container Management
# ============================================================================

@app.get(
    "/api/instances",
    response_model=InstanceListResponse,
    tags=["Instances"]
)
async def list_instances():
    """
    Get Redroid container list.
    
    Note: In host network mode, if Docker socket is unavailable,
    returns an empty instance list (degraded mode).
    """
    try:
        # Check if Docker socket exists
        if not os.path.exists("/var/run/docker.sock"):
            # Docker socket not found, return degraded response
            return InstanceListResponse(
                total=0,
                instances=[],
            )
        
        client = get_docker_client()
        all_containers = client.containers.list(all=True)

        redroid_containers = [
            c for c in all_containers
            if (any("redroid" in tag.lower() for tag in c.image.tags) or
                c.name.startswith("redroid-"))
        ]

        instances = []
        for container in redroid_containers:
            ports = []
            seen_ports = set()  # Used for deduplication
            if container.ports:
                for container_port, host_bindings in container.ports.items():
                    if host_bindings:
                        for binding in host_bindings:
                            port_parts = container_port.split("/")
                            host_port = int(binding.get("HostPort", 0))
                            protocol = port_parts[1] if len(port_parts) > 1 else "tcp"
                            
                            # Deduplication: skip already added (container_port, host_port, protocol) combinations
                            port_key = (int(port_parts[0]), host_port, protocol)
                            if port_key in seen_ports:
                                continue
                            seen_ports.add(port_key)
                            
                            ports.append(PortMapping(
                                container_port=port_key[0],
                                host_port=port_key[1],
                                protocol=port_key[2]
                            ))

            instances.append(ContainerInfo(
                name=container.name,
                id=container.short_id,
                status=container.status,
                state=container.attrs.get("State", {}).get("Status", "unknown"),
                image=container.image.tags[0] if container.image.tags else container.image.short_id,
                ports=ports,
                created_at=container.attrs.get("Created", "unknown")
            ))

        return InstanceListResponse(
            total=len(instances),
            instances=instances
        )

    except docker.errors.DockerException as e:
        # Docker service exception, return degraded response
        return InstanceListResponse(
            total=0,
            instances=[],
        )
    except FileNotFoundError:
        # Docker socket not found
        return InstanceListResponse(
            total=0,
            instances=[],
        )
    except Exception as e:
        # Other exceptions also return degraded response
        return InstanceListResponse(
            total=0,
            instances=[],
        )


@app.get("/api/container/{container_id}/adb_port", tags=["Instances"])
async def get_container_adb_port(container_id: str):
    """Get container's ADB port mapping"""
    try:
        client = get_docker_client()
        container = client.containers.get(container_id)
        ports = container.ports
        port_key = "5555/tcp"

        if ports and port_key in ports:
            host_bindings = ports[port_key]
            if host_bindings and len(host_bindings) > 0:
                return {"port": int(host_bindings[0]["HostPort"])}

        # If no port mapping (host network mode), return default 5555
        return {"port": 5555}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container {container_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get port: {str(e)}")


@app.post(
    "/api/containers/spawn",
    response_model=SpawnResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        500: {"description": "Container creation failed"}
    },
    tags=["Containers"]
)
async def spawn_container(request: SpawnRequest = None):
    """
    Dynamically spawn a new Redroid container
    
    Auto-allocates available ports in range 5555-5600, supports custom resolution and framerate.
    
    Default configuration (optional):
    - width: 720
    - height: 1280
    - fps: 30
    - device_model: Outland_Cloud_Phone
    """
    try:
        docker_manager = get_docker_manager()
        
        # If no request body, use default config
        if request is None:
            result = await docker_manager.spawn_redroid()
        else:
            result = await docker_manager.spawn_redroid(
                width=request.width,
                height=request.height,
                fps=request.fps,
                device_model=request.device_model
            )
        
        return SpawnResponse(
            success=True,
            container_id=result.container_id,
            name=result.name,
            host_port=result.host_port,
            adb_port=result.adb_port,
            message=f"Container created successfully, resolution {request.width if request else 720}x{request.height if request else 1280}@{request.fps if request else 30}Hz"
        )
        
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Container creation failed: {str(e)}"
        )


@app.delete(
    "/api/containers/{container_id}",
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Container not found"},
        500: {"description": "Container deletion failed"}
    },
    tags=["Containers"]
)
async def delete_container(container_id: str, force: bool = True):
    """
    Delete specified container
    
    Args:
        container_id: Container ID or name
        force: Whether to force delete (default True, sends SIGKILL)
    """
    try:
        docker_manager = get_docker_manager()
        docker_manager.delete_container(container_id, force=force)
        
        return {
            "success": True,
            "container_id": container_id,
            "message": "Container deleted"
        }
        
    except docker.errors.NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container {container_id} not found"
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Container deletion failed: {str(e)}"
        )


@app.post(
    "/api/containers/{container_id}/resize",
    response_model=SpawnResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Container not found"},
        500: {"description": "Container resize failed"}
    },
    tags=["Containers"]
)
async def resize_container(container_id: str, request: ResizeRequest):
    """
    Resize a container by recreating it with new resolution
    
    Args:
        container_id: Container ID or name
        request: New configuration (width, height, fps, device_model)
    """
    try:
        docker_manager = get_docker_manager()
        
        result = await docker_manager.resize_container(
            container_id=container_id,
            width=request.width,
            height=request.height,
            fps=request.fps,
            device_model=request.device_model
        )
        
        return SpawnResponse(
            success=True,
            container_id=result.container_id,
            name=result.name,
            host_port=result.host_port,
            adb_port=result.adb_port,
            message=f"Container resized to {request.width}x{request.height}@{request.fps}Hz"
        )
        
    except docker.errors.NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container {container_id} not found"
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Container resize failed: {str(e)}"
        )


# ============================================================================
# API Routes: WebRTC Stream
# ============================================================================

@app.post(
    "/api/stream/webrtc/offer",
    response_model=WebRTCAnswerResponse,
    responses={
        404: {"description": "Container not found"},
        500: {"description": "WebRTC connection establishment failed"}
    },
    tags=["Stream"]
)
async def handle_webrtc_offer(request: WebRTCOfferRequest) -> WebRTCAnswerResponse:
    """
    Handle WebRTC Offer and return Answer
    
    This endpoint:
    1. Gets container's ADB port by container_id
    2. Starts scrcpy video capture
    3. Creates RTCPeerConnection and configures video track
    4. Returns SDP Answer
    
    Control commands are sent via DataChannel in JSON format:
    - Tap: {"action": "click", "x": 100, "y": 200}
    - Swipe: {"action": "swipe", "x1": 100, "y1": 200, "x2": 300, "y2": 400, "duration": 300}
    - Input: {"action": "input", "text": "hello"}
    - KeyEvent: {"action": "keyevent", "keycode": 26}
    """
    try:
        from services.webrtc_manager import get_webrtc_manager
        
        webrtc_manager = get_webrtc_manager()
        answer = await webrtc_manager.handle_offer(
            container_id=request.container_id,
            sdp=request.sdp,
            offer_type=request.type
        )
        
        return WebRTCAnswerResponse(
            sdp=answer.sdp,
            type=answer.type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"WebRTC connection establishment failed: {str(e)}"
        )


class QualityChangeRequest(BaseModel):
    container_id: str
    quality: str = Field(description="Quality level: high, medium, or low")


class QualityChangeResponse(BaseModel):
    success: bool
    container_id: str
    old_quality: str
    new_quality: str
    max_size: int
    bitrate: int


class ConnectionStatsResponse(BaseModel):
    status: str
    available_outgoing_bitrate: Optional[int] = None
    packets_lost: Optional[int] = None
    round_trip_time: Optional[float] = None
    bytes_sent: Optional[int] = None
    error: Optional[str] = None


@app.post(
    "/api/stream/quality",
    response_model=QualityChangeResponse,
    responses={
        404: {"description": "Container not found"},
        500: {"description": "Quality change failed"}
    },
    tags=["Stream"]
)
async def change_quality(request: QualityChangeRequest) -> QualityChangeResponse:
    """
    Change video quality for an active stream.

    This will restart the Scrcpy server with new resolution/bitrate settings.
    The WebRTC connection will need to be reestablished by the client.

    Quality levels:
    - high: 720p (max_size=720, bitrate=2.5Mbps)
    - medium: 480p (max_size=480, bitrate=1.5Mbps)
    - low: 360p (max_size=360, bitrate=800Kbps)
    """
    try:
        from services.webrtc_manager import get_webrtc_manager

        webrtc_manager = get_webrtc_manager()
        result = await webrtc_manager.change_quality(
            container_id=request.container_id,
            quality_name=request.quality
        )

        return QualityChangeResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Quality change failed: {str(e)}"
        )


@app.get(
    "/api/stream/stats/{container_id}",
    response_model=ConnectionStatsResponse,
    responses={
        404: {"description": "Container not found or no active connection"}
    },
    tags=["Stream"]
)
async def get_connection_stats(container_id: str) -> ConnectionStatsResponse:
    """
    Get WebRTC connection statistics for monitoring.

    Returns bandwidth estimation, packet loss, and RTT metrics.
    """
    try:
        from services.webrtc_manager import get_webrtc_manager

        webrtc_manager = get_webrtc_manager()
        stats = await webrtc_manager.get_connection_stats(container_id)

        return ConnectionStatsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get connection stats: {str(e)}"
        )


# ============================================================================
# API Routes: ADB Actions
# ============================================================================

@app.post("/api/action/click", response_model=ActionResponse, tags=["Actions"])
async def click(request: ClickRequest) -> ActionResponse:
    """Execute screen tap action"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.tap(request.container_id, request.x, request.y)
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="click",
            detail=f"Tapped at ({request.x}, {request.y})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tap action failed: {str(e)}"
        )


@app.post("/api/action/swipe", response_model=ActionResponse, tags=["Actions"])
async def swipe(request: SwipeRequest) -> ActionResponse:
    """Execute screen swipe action"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.swipe(
            request.container_id,
            request.x1, request.y1,
            request.x2, request.y2,
            request.duration
        )
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="swipe",
            detail=f"Swiped ({request.x1}, {request.y1}) → ({request.x2}, {request.y2}), duration {request.duration}ms"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Swipe action failed: {str(e)}"
        )


@app.post("/api/action/text", response_model=ActionResponse, tags=["Actions"])
async def text(request: TextRequest) -> ActionResponse:
    """Execute text input action"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.input_text(request.container_id, request.text)
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="text",
            detail=f"Input text: {request.text[:50]}{'...' if len(request.text) > 50 else ''}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Text input failed: {str(e)}"
        )


@app.post("/api/action/keyevent", response_model=ActionResponse, tags=["Actions"])
async def keyevent(request: KeyEventRequest) -> ActionResponse:
    """Execute key event"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.keyevent(request.container_id, request.keycode)
        
        # Common keycode name mapping
        keycode_names = {
            3: "HOME",
            4: "BACK",
            5: "CALL",
            6: "ENDCALL",
            26: "POWER",
            27: "CAMERA",
            66: "ENTER",
            67: "DEL",
        }
        key_name = keycode_names.get(request.keycode, f"KEYCODE_{request.keycode}")
        
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="keyevent",
            detail=f"Key event: {key_name} ({request.keycode})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Key event failed: {str(e)}"
        )


# ============================================================================
# API Routes: APK Installation
# ============================================================================

class ApkInstallResponse(BaseModel):
    """APK installation response model"""
    success: bool
    container_id: str
    message: str


@app.post(
    "/api/apk/install",
    response_model=ApkInstallResponse,
    responses={
        404: {"description": "Container not found"},
        500: {"description": "Installation failed"}
    },
    tags=["APK"]
)
async def install_apk(
    container_id: Annotated[str, Form(description="Docker container ID or name")],
    file: Annotated[UploadFile, File(description="APK or XAPK file")]
) -> ApkInstallResponse:
    """
    Upload and install APK or XAPK file to specified container
    
    Supported file formats:
    - .apk: Standard Android package
    - .xapk: XAPK format (ZIP containing multiple APKs)
    
    Process:
    1. Receive file
    2. Save to temp directory
    3. Call corresponding install method based on file type
    4. Return installation result
    """
    import tempfile
    import os
    
    # Validate file type
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided"
        )
    
    filename_lower = file.filename.lower()
    
    # Support APK and XAPK formats
    if not (filename_lower.endswith('.apk') or filename_lower.endswith('.xapk')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only APK or XAPK files can be uploaded"
        )
    
    # Validate file size (limit 500MB)
    max_size = 500 * 1024 * 1024
    contents = await file.read()
    file_size = len(contents)
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty"
        )
    
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large, max supported is 500MB, current is {file_size / (1024*1024):.2f}MB"
        )
    
    if file_size < 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too small, not a valid APK/XAPK"
        )
    
    # Save to temp file
    file_path = None
    try:
        # Set suffix based on file type
        suffix = '.xapk' if filename_lower.endswith('.xapk') else '.apk'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(contents)
            file_path = tmp.name
        
        logger.info(f"[APK/XAPK Upload] Saved file to temp: {file_path} ({file_size} bytes)")
        
        # Call ADB install
        from services.adb_client import get_adb_manager, AdbOperationError
        
        adb = get_adb_manager()
        
        # Select install method based on file type
        if filename_lower.endswith('.xapk'):
            logger.info(f"[APK/XAPK Upload] Detected XAPK file, calling install_xapk")
            result = await adb.install_xapk(container_id, file_path)
        else:
            logger.info(f"[APK/XAPK Upload] Detected APK file, calling install_apk")
            result = await adb.install_apk(container_id, file_path)
        
        return ApkInstallResponse(
            success=result["success"],
            container_id=container_id,
            message=result["message"]
        )
        
    except AdbOperationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Installation failed: {str(e)}"
        )
    finally:
        # Cleanup temp file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"[APK/XAPK Upload] Deleted temp file: {file_path}")
            except Exception:
                pass


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=9090,
        reload=True,
        log_level="info"
    )
