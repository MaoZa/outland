"""
Outland Agent - 远程 Docker 代理服务

部署在 Redroid 所在的 Ubuntu 服务器上，提供 REST API 供后端查询和管理容器。
轻量级 FastAPI 应用，通过本地 Docker Socket 操作容器。
"""

import docker
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ============================================================================
# Pydantic Models
# ============================================================================

class PortMapping(BaseModel):
    container_port: int
    host_port: int
    protocol: str = "tcp"


class ContainerInfo(BaseModel):
    name: str
    id: str
    status: str
    state: str
    image: str
    ports: List[PortMapping]
    created_at: str


class InstanceListResponse(BaseModel):
    total: int
    instances: List[ContainerInfo]


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Outland Agent",
    description="远程 Docker 代理，为 Outland 后端提供容器查询服务",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_docker_client() -> docker.DockerClient:
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker 连接失败: {str(e)}")


# ============================================================================
# API Routes
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    try:
        client = get_docker_client()
        return {"status": "ok", "docker": "connected"}
    except Exception:
        return {"status": "degraded", "docker": "disconnected"}


@app.get("/api/instances", response_model=InstanceListResponse)
async def list_instances():
    """获取本机上运行的 Redroid 容器列表"""
    try:
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

        return InstanceListResponse(total=len(instances), instances=instances)

    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=f"Docker 异常: {str(e)}")


@app.get("/api/container/{container_id}/adb_port")
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

        raise HTTPException(status_code=500, detail=f"容器 {container_id} 未暴露 5555/tcp 端口")

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"容器 {container_id} 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取端口失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=9090, log_level="info")
