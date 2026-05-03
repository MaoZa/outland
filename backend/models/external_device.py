from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ExternalDeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Device name / remark")
    adb_host: str = Field(..., min_length=1, max_length=255, description="ADB host address")
    adb_port: int = Field(5555, ge=1, le=65535, description="ADB port")
    agent_id: Optional[str] = Field(None, description="Agent ID (auto-select if null)")


class ExternalDeviceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    adb_host: Optional[str] = Field(None, min_length=1, max_length=255)
    adb_port: Optional[int] = Field(None, ge=1, le=65535)
    agent_id: Optional[str] = Field(None)


class ExternalDeviceResponse(BaseModel):
    id: int
    uuid: str
    name: str
    adb_host: str
    adb_port: int
    agent_id: Optional[str] = None
    has_rsa_key: bool = False
    status: str = "active"
    resolution: str = "720x1280"
    created_at: datetime

    class Config:
        from_attributes = True


class ExternalDeviceTestResponse(BaseModel):
    success: bool
    message: str = ""
