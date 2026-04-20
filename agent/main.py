"""
Outland Agent - Main Application Entry Point

轻量级 FastAPI 应用，部署在 Redroid 所在的物理机上。
提供 WebRTC 流媒体、ADB 控制和容器管理功能。

核心接口：
- GET  /health                    → 健康检查
- POST /api/stream/webrtc/offer   → WebRTC 握手处理
- POST /api/action/click          → ADB 点击
- POST /api/action/swipe          → ADB 滑动
- POST /api/action/text           → ADB 文本输入
- POST /api/action/keyevent       → ADB 按键
- GET  /api/instances             → 容器列表
- GET  /api/container/{id}/adb_port → 获取容器 ADB 端口
"""

import logging
import os
import docker
from contextlib import asynccontextmanager
from typing import Annotated, List, Optional

# 配置全局 logging，确保 ScrcpyTrack / WebRTC 等模块的日志正常输出
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
# 降低第三方库的噪声日志级别
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.INFO)
logging.getLogger("av").setLevel(logging.WARNING)

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.webrtc_manager import shutdown_webrtc_manager


# ============================================================================
# Pydantic Models
# ============================================================================

class PortMapping(BaseModel):
    """端口映射模型"""
    container_port: int
    host_port: int
    protocol: str = "tcp"


class ContainerInfo(BaseModel):
    """容器信息模型"""
    name: str
    id: str
    status: str
    state: str
    image: str
    ports: List[PortMapping]
    created_at: str


class InstanceListResponse(BaseModel):
    """实例列表响应模型"""
    total: int
    instances: List[ContainerInfo]


# ============================================================================
# WebRTC Models
# ============================================================================

class WebRTCOfferRequest(BaseModel):
    """WebRTC Offer 请求模型"""
    container_id: str
    sdp: str
    type: str = "offer"


class WebRTCAnswerResponse(BaseModel):
    """WebRTC Answer 响应模型"""
    sdp: str
    type: str


# ============================================================================
# Action Models
# ============================================================================

class ClickRequest(BaseModel):
    """点击操作请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    x: Annotated[int, Field(description="点击的 X 坐标", ge=0)]
    y: Annotated[int, Field(description="点击的 Y 坐标", ge=0)]


class SwipeRequest(BaseModel):
    """滑动操作请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    x1: Annotated[int, Field(description="起始 X 坐标", ge=0)]
    y1: Annotated[int, Field(description="起始 Y 坐标", ge=0)]
    x2: Annotated[int, Field(description="结束 X 坐标", ge=0)]
    y2: Annotated[int, Field(description="结束 Y 坐标", ge=0)]
    duration: Annotated[int, Field(description="滑动持续时间（毫秒）", ge=0, default=300)]


class TextRequest(BaseModel):
    """文本输入请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    text: Annotated[str, Field(description="要输入的文本内容")]


class KeyEventRequest(BaseModel):
    """按键事件请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    keycode: Annotated[int, Field(description="Android 按键码（如 26=POWER, 4=BACK, 3=HOME）")]


class ActionResponse(BaseModel):
    """操作成功响应模型"""
    success: bool = True
    container_id: str
    action: str
    detail: str = ""


# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    print("[Outland Agent] Starting up...")
    yield
    # Shutdown: 清理 WebRTC 和 ADB 资源
    print("[Outland Agent] Shutting down...")
    await shutdown_webrtc_manager()


app = FastAPI(
    title="Outland Agent",
    description="远程安卓云容器代理，提供 WebRTC 流媒体和 ADB 控制服务",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Docker Client Helper
# ============================================================================

def get_docker_client() -> docker.DockerClient:
    """
    获取 Docker 客户端实例。
    
    Returns:
        docker.DockerClient: Docker 客户端
        
    Raises:
        HTTPException: Docker 连接失败时抛出
    """
    try:
        client = docker.from_env()
        client.ping()
        return client
    except docker.errors.DockerException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Docker 服务未启动或无法连接: {str(e)}"
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=500,
            detail=f"缺少 Docker 操作权限，请确保用户具有 docker 组权限: {str(e)}"
        )


# ============================================================================
# API Routes: Health
# ============================================================================

@app.get("/", tags=["Health"])
async def root():
    """服务根路径"""
    return {"status": "ok", "service": "outland-agent"}


@app.get("/health", tags=["Health"])
async def health_check():
    """详细健康检查（包含 Docker 状态）"""
    try:
        client = get_docker_client()
        docker_info = client.info()
        return {
            "status": "healthy",
            "docker": "connected",
            "docker_version": docker_info.get("ServerVersion", "unknown")
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
    获取 Redroid 容器列表。
    
    注意：在 host 网络模式下，如果 Docker socket 不可用，
    返回空的实例列表（降级模式）。
    """
    try:
        # 检查 Docker socket 是否存在
        if not os.path.exists("/var/run/docker.sock"):
            # Docker socket 不存在，返回降级响应
            return InstanceListResponse(
                total=0,
                instances=[],
                degraded=True,
                message="Docker socket 不可用，运行在降级模式"
            )
        
        client = get_docker_client()
        all_containers = client.containers.list(all=True)

        redroid_containers = [
            c for c in all_containers
            if any("redroid" in tag.lower() for tag in c.image.tags)
        ]

        instances = []
        for container in redroid_containers:
            ports = []
            if container.ports:
                for container_port, host_bindings in container.ports.items():
                    if host_bindings:
                        for binding in host_bindings:
                            port_parts = container_port.split("/")
                            ports.append(PortMapping(
                                container_port=int(port_parts[0]),
                                host_port=int(binding.get("HostPort", 0)),
                                protocol=port_parts[1] if len(port_parts) > 1 else "tcp"
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
        # Docker 服务异常，返回降级响应
        return InstanceListResponse(
            total=0,
            instances=[],
            degraded=True,
            message=f"Docker 服务异常: {str(e)}"
        )
    except FileNotFoundError:
        # Docker socket 不存在
        return InstanceListResponse(
            total=0,
            instances=[],
            degraded=True,
            message="Docker socket 不存在"
        )
    except Exception as e:
        # 其他异常也返回降级响应
        return InstanceListResponse(
            total=0,
            instances=[],
            degraded=True,
            message=f"获取容器列表失败: {str(e)}"
        )


@app.get("/api/container/{container_id}/adb_port", tags=["Instances"])
async def get_container_adb_port(container_id: str):
    """获取容器的 ADB 端口映射"""
    try:
        client = get_docker_client()
        container = client.containers.get(container_id)
        ports = container.ports
        port_key = "5555/tcp"

        if ports and port_key in ports:
            host_bindings = ports[port_key]
            if host_bindings and len(host_bindings) > 0:
                return {"port": int(host_bindings[0]["HostPort"])}

        # 如果没有端口映射（host 网络模式），默认返回 5555
        return {"port": 5555}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"容器 {container_id} 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取端口失败: {str(e)}")


# ============================================================================
# API Routes: WebRTC Stream
# ============================================================================

@app.post(
    "/api/stream/webrtc/offer",
    response_model=WebRTCAnswerResponse,
    responses={
        404: {"description": "容器不存在"},
        500: {"description": "WebRTC 连接建立失败"}
    },
    tags=["Stream"]
)
async def handle_webrtc_offer(request: WebRTCOfferRequest) -> WebRTCAnswerResponse:
    """
    处理 WebRTC Offer 并返回 Answer
    
    此接口会：
    1. 根据 container_id 获取容器的 ADB 端口
    2. 启动 scrcpy 视频捕获
    3. 创建 RTCPeerConnection 并配置视频轨道
    4. 返回 SDP Answer
    
    控制指令通过 DataChannel 发送，格式为 JSON：
    - 点击: {"action": "click", "x": 100, "y": 200}
    - 滑动: {"action": "swipe", "x1": 100, "y1": 200, "x2": 300, "y2": 400, "duration": 300}
    - 输入: {"action": "input", "text": "hello"}
    - 按键: {"action": "keyevent", "keycode": 26}
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
            detail=f"WebRTC 连接建立失败: {str(e)}"
        )


# ============================================================================
# API Routes: ADB Actions
# ============================================================================

@app.post("/api/action/click", response_model=ActionResponse, tags=["Actions"])
async def click(request: ClickRequest) -> ActionResponse:
    """执行屏幕点击操作"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.tap(request.container_id, request.x, request.y)
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="click",
            detail=f"点击坐标 ({request.x}, {request.y})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"点击操作失败: {str(e)}"
        )


@app.post("/api/action/swipe", response_model=ActionResponse, tags=["Actions"])
async def swipe(request: SwipeRequest) -> ActionResponse:
    """执行屏幕滑动操作"""
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
            detail=f"滑动 ({request.x1}, {request.y1}) → ({request.x2}, {request.y2}), 耗时 {request.duration}ms"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"滑动操作失败: {str(e)}"
        )


@app.post("/api/action/text", response_model=ActionResponse, tags=["Actions"])
async def text(request: TextRequest) -> ActionResponse:
    """执行文本输入操作"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.input_text(request.container_id, request.text)
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="text",
            detail=f"输入文本: {request.text[:50]}{'...' if len(request.text) > 50 else ''}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文本输入失败: {str(e)}"
        )


@app.post("/api/action/keyevent", response_model=ActionResponse, tags=["Actions"])
async def keyevent(request: KeyEventRequest) -> ActionResponse:
    """执行按键事件"""
    try:
        from services.adb_client import get_adb_manager
        
        adb = get_adb_manager()
        await adb.keyevent(request.container_id, request.keycode)
        
        # 常用按键码名称映射
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
            detail=f"按键事件: {key_name} ({request.keycode})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"按键事件失败: {str(e)}"
        )


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
