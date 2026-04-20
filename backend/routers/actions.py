import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from auth.dependencies import get_current_user
from database import get_db
from database.models import User, Container
from models import (
    ClickRequest, SwipeRequest, TextRequest,
    KeyEventRequest, ActionResponse
)
from services import get_agent_url
from core.http_client import get_http_client

router = APIRouter(prefix="/api/action", tags=["Actions"])


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


async def _forward_action(
    db: AsyncSession,
    current_user: User,
    action: str,
    container_id: str,
    agent_id: Optional[str],
    payload: dict
) -> ActionResponse:
    db_container = await verify_container_ownership(db, container_id, current_user)
    agent_id = agent_id or db_container.agent_id

    try:
        agent_url, actual_agent_id = get_agent_url(agent_id)

        resp = await get_http_client().post(
            f"{agent_url}/api/action/{action}",
            json={**payload, "container_id": container_id},
            timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()

        return ActionResponse(
            success=data.get("success", True),
            container_id=container_id,
            action=action,
            detail=data.get("detail", "")
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Action request failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )


@router.post("/click", response_model=ActionResponse)
async def click(
    request: ClickRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ActionResponse:
    return await _forward_action(
        db, current_user,
        "click",
        request.container_id,
        request.agent_id,
        {"x": request.x, "y": request.y}
    )


@router.post("/swipe", response_model=ActionResponse)
async def swipe(
    request: SwipeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ActionResponse:
    return await _forward_action(
        db, current_user,
        "swipe",
        request.container_id,
        request.agent_id,
        {
            "x1": request.x1,
            "y1": request.y1,
            "x2": request.x2,
            "y2": request.y2,
            "duration": request.duration
        }
    )


@router.post("/text", response_model=ActionResponse)
async def text(
    request: TextRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ActionResponse:
    return await _forward_action(
        db, current_user,
        "text",
        request.container_id,
        request.agent_id,
        {"text": request.text}
    )


@router.post("/keyevent", response_model=ActionResponse)
async def keyevent(
    request: KeyEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ActionResponse:
    return await _forward_action(
        db, current_user,
        "keyevent",
        request.container_id,
        request.agent_id,
        {"keycode": request.keycode}
    )
