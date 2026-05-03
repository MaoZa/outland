from pydantic import BaseModel, Field
from typing import List, Optional


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
    source: Optional[str] = None
    agent_id: Optional[str] = None
    adb_address: Optional[str] = None
    has_rsa_key: bool = False


class InstanceListResponse(BaseModel):
    total: int
    instances: List[ContainerInfo]


class ErrorResponse(BaseModel):
    error: str
    detail: str


class SpawnRequest(BaseModel):
    agent_id: Optional[str] = Field(None, description="Target Agent ID (uses default Agent if not specified)")
    width: int = Field(720, ge=320, le=3840, description="Screen width")
    height: int = Field(1280, ge=480, le=2160, description="Screen height")
    fps: int = Field(30, ge=1, le=60, description="Framerate")
    device_model: str = Field("Outland_Cloud_Phone", description="Device model")


class SpawnResponse(BaseModel):
    success: bool
    container_id: str
    name: str
    host_port: int
    adb_port: int = 5555
    message: str = ""


class DeleteContainerRequest(BaseModel):
    agent_id: Optional[str] = Field(None, description="Target Agent ID")


class DeleteContainerResponse(BaseModel):
    success: bool
    container_id: str
    message: str


class ResizeRequest(BaseModel):
    agent_id: Optional[str] = Field(None, description="Target Agent ID (uses default Agent if not specified)")
    width: int = Field(720, ge=320, le=3840, description="Screen width")
    height: int = Field(1280, ge=480, le=2160, description="Screen height")
    fps: int = Field(30, ge=1, le=60, description="Framerate")
    device_model: str = Field("Outland_Cloud_Phone", description="Device model")
