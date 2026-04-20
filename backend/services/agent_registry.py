import asyncio
import time
from typing import Dict, List, Optional, Tuple

from core.config import settings
from core.http_client import get_http_client


AGENT_REGISTRY: Dict[str, dict] = {}


async def agent_cleanup_loop():
    while True:
        await asyncio.sleep(settings.HEARTBEAT_CLEANUP_INTERVAL)
        try:
            await cleanup_stale_agents()
        except Exception as e:
            print(f"[Outland] Agent cleanup error: {e}")


async def cleanup_stale_agents():
    current_time = time.time()
    stale_agents = []

    for agent_id, info in list(AGENT_REGISTRY.items()):
        last_heartbeat = info.get("last_heartbeat", 0)
        if current_time - last_heartbeat > settings.HEARTBEAT_TIMEOUT:
            stale_agents.append(agent_id)

    for agent_id in stale_agents:
        del AGENT_REGISTRY[agent_id]
        print(f"[Outland] Removed stale agent: {agent_id}")

    if stale_agents:
        print(f"[Outland] Cleaned up {len(stale_agents)} stale agent(s)")


async def fetch_agent_instances(agent_url: str, agent_id: str) -> List[dict]:
    try:
        resp = await get_http_client().get(
            f"{agent_url}/api/instances",
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()

        for instance in data.get("instances", []):
            instance["source"] = f"agent-{agent_id}"
            instance["agent_id"] = agent_id

        return data.get("instances", [])
    except Exception as e:
        print(f"[Outland] Failed to fetch instances from {agent_url}: {e}")
        return []


def get_agent_url(agent_id: Optional[str] = None) -> Tuple[str, str]:
    if agent_id:
        if agent_id not in AGENT_REGISTRY:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail=f"Agent {agent_id} not registered or offline"
            )
        return AGENT_REGISTRY[agent_id]["url"], agent_id
    else:
        if not AGENT_REGISTRY:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=503,
                detail="No available Agent, ensure Agent is started and registered first"
            )
        first_agent_id = next(iter(AGENT_REGISTRY.keys()))
        return AGENT_REGISTRY[first_agent_id]["url"], first_agent_id
