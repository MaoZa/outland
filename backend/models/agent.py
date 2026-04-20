from pydantic import BaseModel, Field
from typing import List


class AgentRegisterRequest(BaseModel):
    agent_id: str = Field(description="Agent unique identifier (hostname or UUID)")
    url: str = Field(description="Agent access URL")


class AgentHeartbeatRequest(BaseModel):
    agent_id: str = Field(description="Agent unique identifier")


class AgentInfo(BaseModel):
    agent_id: str
    url: str
    last_heartbeat: float


class AgentRegistryResponse(BaseModel):
    agents: List[AgentInfo]
    total: int
