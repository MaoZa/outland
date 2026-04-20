import time
from fastapi import APIRouter, HTTPException, Depends
from typing import List

from auth.dependencies import get_current_user
from database.models import User
from models import AgentRegisterRequest, AgentHeartbeatRequest, AgentInfo, AgentRegistryResponse
from services import AGENT_REGISTRY

router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.post("/register")
async def register_agent(request: AgentRegisterRequest):
    current_time = time.time()

    existing_agent_id = None
    for agent_id, info in list(AGENT_REGISTRY.items()):
        if info["url"] == request.url:
            existing_agent_id = agent_id
            break

    if existing_agent_id:
        AGENT_REGISTRY[existing_agent_id]["last_heartbeat"] = current_time
        print(f"[Outland] Agent updated: {existing_agent_id} at {request.url}")
        return {
            "success": True,
            "agent_id": existing_agent_id,
            "message": "Registration updated successfully"
        }
    else:
        AGENT_REGISTRY[request.agent_id] = {
            "url": request.url,
            "last_heartbeat": current_time
        }
        print(f"[Outland] Agent registered: {request.agent_id} at {request.url}")
        return {
            "success": True,
            "agent_id": request.agent_id,
            "message": "Registration successful"
        }


@router.post("/heartbeat")
async def agent_heartbeat(request: AgentHeartbeatRequest):
    agent_id = request.agent_id

    if agent_id in AGENT_REGISTRY:
        AGENT_REGISTRY[agent_id]["last_heartbeat"] = time.time()
        return {
            "success": True,
            "agent_id": agent_id,
            "message": "Heartbeat updated successfully"
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not registered, please call /api/agents/register first"
        )


@router.get("/list", response_model=AgentRegistryResponse)
async def list_agents(current_user: User = Depends(get_current_user)):
    agents = []
    current_time = time.time()

    for agent_id, info in AGENT_REGISTRY.items():
        agents.append(AgentInfo(
            agent_id=agent_id,
            url=info["url"],
            last_heartbeat=info["last_heartbeat"]
        ))

    return AgentRegistryResponse(
        agents=agents,
        total=len(agents)
    )
