import asyncio
import docker
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Set, Dict

from auth.dependencies import get_current_user
from database import get_db
from database.models import User, Container, ExternalDevice
from models import PortMapping, ContainerInfo, InstanceListResponse, ErrorResponse
from services import AGENT_REGISTRY, fetch_agent_instances

router = APIRouter(prefix="/api", tags=["Instances"])


@router.get("/instances", response_model=InstanceListResponse, responses={500: {"model": ErrorResponse}})
async def list_instances(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Container).where(
            Container.user_id == current_user.id,
            Container.status.in_(["running", "pending"])
        )
    )
    user_containers = result.scalars().all()

    ext_result = await db.execute(
        select(ExternalDevice).where(
            ExternalDevice.user_id == current_user.id,
            ExternalDevice.status == "active",
        )
    )
    external_devices = ext_result.scalars().all()

    if not user_containers and not external_devices:
        return InstanceListResponse(total=0, instances=[])

    agent_live_data: Dict[str, dict] = {}

    if AGENT_REGISTRY:
        tasks = [
            fetch_agent_instances(info["url"], agent_id)
            for agent_id, info in AGENT_REGISTRY.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for agent_result in results:
            if isinstance(agent_result, list):
                for instance in agent_result:
                    cid = instance.get("id") or instance.get("container_id")
                    if cid:
                        agent_live_data[cid] = instance
                        if len(cid) > 12:
                            agent_live_data[cid[:12]] = instance

    all_instances = []
    seen_container_ids: Set[str] = set()

    for c in user_containers:
        if c.container_id in seen_container_ids:
            continue
        seen_container_ids.add(c.container_id)

        short_id = c.container_id[:12] if len(c.container_id) > 12 else c.container_id
        live = agent_live_data.get(c.container_id) or agent_live_data.get(short_id)

        if live:
            all_instances.append({
                "name": live.get("name", c.container_id[:12]),
                "id": c.container_id,
                "status": live.get("status", c.status),
                "state": live.get("state", c.status),
                "image": live.get("image", "unknown"),
                "ports": live.get("ports", []),
                "created_at": live.get("created_at", str(c.created_at)),
                "source": "docker",
                "agent_id": c.agent_id,
            })
        else:
            all_instances.append({
                "name": c.container_id[:12],
                "id": c.container_id,
                "status": c.status,
                "state": c.status,
                "image": "unknown",
                "ports": [],
                "created_at": str(c.created_at),
                "source": "docker",
                "agent_id": c.agent_id,
            })

    for d in external_devices:
        all_instances.append({
            "name": d.name,
            "id": d.uuid,
            "status": "running",
            "state": "external",
            "image": "external-device",
            "ports": [{"container_port": d.adb_port, "host_port": d.adb_port, "protocol": "tcp"}],
            "created_at": str(d.created_at),
            "source": "external",
            "agent_id": d.agent_id,
            "adb_address": f"{d.adb_host}:{d.adb_port}",
            "has_rsa_key": bool(d.rsa_key_path),
        })

    return InstanceListResponse(
        total=len(all_instances),
        instances=all_instances
    )
