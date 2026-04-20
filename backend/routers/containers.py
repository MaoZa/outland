import uuid
import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Optional

from auth.dependencies import get_current_user
from database import get_db
from database.models import User, Container, Quota
from models import (
    SpawnRequest, SpawnResponse,
    DeleteContainerRequest, DeleteContainerResponse,
    ResizeRequest
)
from services import get_agent_url
from core.http_client import get_http_client

router = APIRouter(prefix="/api/containers", tags=["Containers"])


async def get_user_container(db: AsyncSession, docker_container_id: str, user: User) -> Container:
    result = await db.execute(
        select(Container).where(
            Container.container_id == docker_container_id,
            Container.user_id == user.id
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or not owned by you")
    return container


@router.post("/spawn", response_model=SpawnResponse)
async def spawn_container(
    request: SpawnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    quota_result = await db.execute(
        select(Quota).where(Quota.user_id == current_user.id)
    )
    quota = quota_result.scalar_one_or_none()
    if not quota:
        raise HTTPException(status_code=403, detail="User quota not found")

    count_result = await db.execute(
        select(func.count(Container.id)).where(
            Container.user_id == current_user.id,
            Container.status.in_(["running", "pending"])
        )
    )
    active_count = count_result.scalar() or 0
    if active_count >= quota.max_containers:
        raise HTTPException(
            status_code=403,
            detail=f"Container quota exceeded (max: {quota.max_containers}, current: {active_count})"
        )

    try:
        agent_url, agent_id = get_agent_url(request.agent_id)

        resp = await get_http_client().post(
            f"{agent_url}/api/containers/spawn",
            json={
                "width": request.width,
                "height": request.height,
                "fps": request.fps,
                "device_model": request.device_model
            },
            timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()

        docker_container_id = data.get("container_id", "")

        db_container = Container(
            uuid=str(uuid.uuid4()),
            user_id=current_user.id,
            agent_id=agent_id,
            container_id=docker_container_id,
            status="running",
            resolution=f"{request.width}x{request.height}"
        )
        db.add(db_container)
        await db.commit()

        return SpawnResponse(
            success=data.get("success", True),
            container_id=docker_container_id,
            name=data.get("name", ""),
            host_port=data.get("host_port", 0),
            adb_port=data.get("adb_port", 5555),
            message=f"Container created successfully (Agent: {agent_id})"
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Agent request failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )


@router.delete("/{container_id}", response_model=DeleteContainerResponse)
async def delete_container(
    container_id: str,
    request: DeleteContainerRequest = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    db_container = await get_user_container(db, container_id, current_user)

    agent_id = request.agent_id if request else db_container.agent_id

    try:
        agent_url, actual_agent_id = get_agent_url(agent_id)

        resp = await get_http_client().delete(
            f"{agent_url}/api/containers/{container_id}?force=true",
            timeout=30.0
        )
        resp.raise_for_status()

        db_container.status = "deleted"
        await db.commit()

        return DeleteContainerResponse(
            success=True,
            container_id=container_id,
            message=f"Container deleted (Agent: {actual_agent_id})"
        )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            db_container.status = "deleted"
            await db.commit()
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Agent request failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )


@router.post("/{container_id}/resize", response_model=SpawnResponse)
async def resize_container(
    container_id: str,
    request: ResizeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    db_container = await get_user_container(db, container_id, current_user)

    agent_id = request.agent_id if request else db_container.agent_id

    try:
        agent_url, agent_id = get_agent_url(agent_id)

        resp = await get_http_client().post(
            f"{agent_url}/api/containers/{container_id}/resize",
            json={
                "width": request.width,
                "height": request.height,
                "fps": request.fps,
                "device_model": request.device_model
            },
            timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()

        db_container.resolution = f"{request.width}x{request.height}"
        await db.commit()

        return SpawnResponse(
            success=data.get("success", True),
            container_id=data.get("container_id", ""),
            name=data.get("name", ""),
            host_port=data.get("host_port", 0),
            adb_port=data.get("adb_port", 5555),
            message=f"Container resized (Agent: {agent_id})"
        )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Container {container_id} not found"
            )
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Agent request failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )


@router.get("/{container_id}/adb_port")
async def get_container_adb_port(
    container_id: str,
    agent_id: str = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await get_user_container(db, container_id, current_user)

    try:
        agent_url, actual_agent_id = get_agent_url(agent_id)

        resp = await get_http_client().get(
            f"{agent_url}/api/container/{container_id}/adb_port",
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Agent request failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )
