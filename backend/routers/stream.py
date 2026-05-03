import httpx
import os
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from auth.dependencies import get_current_user
from database import get_db
from database.models import User, Container, ExternalDevice
from models import (
    WebRTCOfferRequest, WebRTCAnswerResponse,
    QualityChangeRequest, QualityChangeResponse,
    ConnectionStatsResponse
)
from services import get_agent_url, AGENT_REGISTRY
from core.http_client import get_http_client
from .external_device_helpers import is_external_device, get_external_device, resolve_agent_for_device

router = APIRouter(prefix="/api/stream", tags=["Stream"])


async def verify_container_ownership(db: AsyncSession, container_id: str, user: User) -> Container:
    result = await db.execute(
        select(Container).where(
            Container.container_id == container_id,
            Container.user_id == user.id,
            Container.status.in_(["running", "pending"])
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found or not owned by you")
    return container


@router.post("/webrtc/offer", response_model=WebRTCAnswerResponse)
async def handle_webrtc_offer(
    request: WebRTCOfferRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if is_external_device(request.container_id):
        device = await get_external_device(db, request.container_id, current_user)
        agent_url, agent_id = await resolve_agent_for_device(device.agent_id)
        adb_address = f"{device.adb_host}:{device.adb_port}"

        rsa_key_content = None
        if device.rsa_key_path and os.path.exists(device.rsa_key_path):
            with open(device.rsa_key_path, "r") as f:
                rsa_key_content = f.read()

        try:
            resp = await get_http_client().post(
                f"{agent_url}/api/stream/webrtc/offer",
                json={
                    "container_id": request.container_id,
                    "sdp": request.sdp,
                    "type": request.type,
                    "external_adb_address": adb_address,
                    "rsa_key_content": rsa_key_content,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return WebRTCAnswerResponse(
                sdp=data.get("sdp", ""),
                type=data.get("type", "answer"),
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"WebRTC processing failed: {e.response.text}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot connect to Agent: {str(e)}",
            )

    db_container = await verify_container_ownership(db, request.container_id, current_user)
    agent_id = request.agent_id or db_container.agent_id

    try:
        agent_url, agent_id = get_agent_url(agent_id)

        resp = await get_http_client().post(
            f"{agent_url}/api/stream/webrtc/offer",
            json={
                "container_id": request.container_id,
                "sdp": request.sdp,
                "type": request.type
            },
            timeout=60.0
        )
        resp.raise_for_status()
        data = resp.json()

        return WebRTCAnswerResponse(
            sdp=data.get("sdp", ""),
            type=data.get("type", "answer")
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"WebRTC processing failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )


@router.post("/quality", response_model=QualityChangeResponse)
async def change_quality(
    request: QualityChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if is_external_device(request.container_id):
        device = await get_external_device(db, request.container_id, current_user)
        agent_url, agent_id = await resolve_agent_for_device(device.agent_id)
        adb_address = f"{device.adb_host}:{device.adb_port}"

        rsa_key_content = None
        if device.rsa_key_path and os.path.exists(device.rsa_key_path):
            with open(device.rsa_key_path, "r") as f:
                rsa_key_content = f.read()

        try:
            resp = await get_http_client().post(
                f"{agent_url}/api/stream/quality",
                json={
                    "container_id": request.container_id,
                    "quality": request.quality,
                    "external_adb_address": adb_address,
                    "rsa_key_content": rsa_key_content,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return QualityChangeResponse(
                success=data.get("success", True),
                container_id=data.get("container_id", ""),
                old_quality=data.get("old_quality", ""),
                new_quality=data.get("new_quality", ""),
                max_size=data.get("max_size", 0),
                bitrate=data.get("bitrate", 0),
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Quality change failed: {e.response.text}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot connect to Agent: {str(e)}",
            )

    db_container = await verify_container_ownership(db, request.container_id, current_user)

    try:
        agent_url, agent_id = get_agent_url(db_container.agent_id)

        resp = await get_http_client().post(
            f"{agent_url}/api/stream/quality",
            json={
                "container_id": request.container_id,
                "quality": request.quality
            },
            timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()

        return QualityChangeResponse(
            success=data.get("success", True),
            container_id=data.get("container_id", ""),
            old_quality=data.get("old_quality", ""),
            new_quality=data.get("new_quality", ""),
            max_size=data.get("max_size", 0),
            bitrate=data.get("bitrate", 0)
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Quality change failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )


@router.get("/stats/{container_id}", response_model=ConnectionStatsResponse)
async def get_connection_stats(
    container_id: str,
    agent_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if is_external_device(container_id):
        device = await get_external_device(db, container_id, current_user)
        agent_url, _ = await resolve_agent_for_device(device.agent_id)
    else:
        db_container = await verify_container_ownership(db, container_id, current_user)
        agent_id = agent_id or db_container.agent_id
        agent_url, _ = get_agent_url(agent_id)

    try:
        resp = await get_http_client().get(
            f"{agent_url}/api/stream/stats/{container_id}",
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()

        return ConnectionStatsResponse(
            status=data.get("status", "unknown"),
            available_outgoing_bitrate=data.get("available_outgoing_bitrate"),
            packets_lost=data.get("packets_lost"),
            round_trip_time=data.get("round_trip_time"),
            bytes_sent=data.get("bytes_sent"),
            error=data.get("error")
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to get stats: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )
