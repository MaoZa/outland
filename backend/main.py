"""
Outland Backend - Main Application Entry Point

一个基于 FastAPI 的安卓云容器管理平台后端。
提供 Redroid 容器管理、ADB 控制、脚本自动化等功能。
"""

import docker
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


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


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str
    detail: str


# ============================================================================
# Docker Client Initialization
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
        # 测试连接
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
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup: 初始化资源
    print("[Outland] Backend starting up...")
    yield
    # Shutdown: 清理资源
    print("[Outland] Backend shutting down...")


app = FastAPI(
    title="Outland API",
    description="安卓云容器管理平台后端 API",
    version="0.1.0",
    lifespan=lifespan
)

# ============================================================================
# CORS Middleware Configuration
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js 开发服务器
        "http://127.0.0.1:3000",
        # 生产环境可添加实际的前端域名
        # "https://your-frontend-domain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API Routes
# ============================================================================

from backend.routers import automation

app.include_router(automation.router, prefix="/api/action", tags=["Automation"])

@app.get("/", tags=["Health"])
async def root():
    """服务健康检查"""
    return {"status": "ok", "service": "outland-backend"}


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


@app.get(
    "/api/instances",
    response_model=InstanceListResponse,
    responses={500: {"model": ErrorResponse}},
    tags=["Instances"]
)
async def list_instances():
    """
    获取当前宿主机上运行的 Redroid 容器列表。
    
    返回所有 Redroid 镜像的容器及其状态信息，包括：
    - 容器名称、ID、运行状态
    - 端口映射信息
    - 创建时间
    
    Returns:
        InstanceListResponse: 包含容器总数和实例列表
        
    Raises:
        HTTPException 500: Docker 服务未启动或权限不足
    """
    try:
        client = get_docker_client()
        
        # 过滤 redroid 相关的容器
        # 支持的镜像名模式：redroid/redroid:*、redroid/*
        all_containers = client.containers.list(all=True)
        
        redroid_containers = [
            c for c in all_containers
            if any("redroid" in tag.lower() for tag in c.image.tags)
        ]
        
        instances = []
        for container in redroid_containers:
            # 获取端口映射
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
        raise HTTPException(
            status_code=500,
            detail=f"Docker 服务异常: {str(e)}"
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=500,
            detail=f"缺少 Docker 操作权限: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取容器列表失败: {str(e)}"
        )


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
