from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database.models import User, ExternalDevice
from services import get_agent_url, AGENT_REGISTRY


def is_external_device(container_id: str) -> bool:
    return container_id.startswith("ext_")


async def get_external_device(
    db: AsyncSession, device_uuid: str, user: User
) -> ExternalDevice:
    result = await db.execute(
        select(ExternalDevice).where(
            ExternalDevice.uuid == device_uuid,
            ExternalDevice.user_id == user.id,
            ExternalDevice.status == "active",
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="External device not found")
    return device


async def resolve_agent_for_device(agent_id: Optional[str] = None) -> tuple[str, str]:
    if not agent_id and AGENT_REGISTRY:
        agent_id = next(iter(AGENT_REGISTRY))
    try:
        return get_agent_url(agent_id)
    except HTTPException:
        raise HTTPException(status_code=503, detail="No available Agent")
