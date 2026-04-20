import httpx
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Optional

from auth.dependencies import get_current_user
from database import get_db
from database.models import User, Container
from models import ApkInstallResponse
from services import get_agent_url
from core.http_client import get_http_client

router = APIRouter(prefix="/api/apk", tags=["APK"])


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


@router.post("/install", response_model=ApkInstallResponse)
async def install_apk(
    container_id: Annotated[str, Form(description="Docker container ID or name")],
    file: Annotated[UploadFile, File(description="APK file")],
    agent_id: Annotated[Optional[str], Form(description="Agent ID (optional)")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    db_container = await verify_container_ownership(db, container_id, current_user)
    agent_id = agent_id or db_container.agent_id

    if not file:
        raise HTTPException(status_code=400, detail="APK file must be provided")

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith('.apk') or filename_lower.endswith('.xapk')):
        raise HTTPException(status_code=400, detail="Only APK or XAPK files can be uploaded")

    try:
        agent_url, actual_agent_id = get_agent_url(agent_id)

        file_content = await file.read()
        file_size = len(file_content)

        max_size = 500 * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(status_code=400, detail=f"APK file too large, max supported is {max_size // (1024*1024)}MB")

        if file_size < 1024:
            raise HTTPException(status_code=400, detail="File too small, not a valid APK")

        form_data = {
            "container_id": (None, container_id),
            "file": (file.filename, file_content, "application/vnd.android.package-archive")
        }

        resp = await get_http_client().post(
            f"{agent_url}/api/apk/install",
            files=form_data,
            timeout=180.0
        )
        resp.raise_for_status()
        data = resp.json()

        return ApkInstallResponse(
            success=data.get("success", True),
            container_id=container_id,
            message=data.get("message", "")
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"APK installation failed: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Agent: {str(e)}"
        )
