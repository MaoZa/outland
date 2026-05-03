import os
import uuid
import httpx
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from auth.dependencies import get_current_user
from database import get_db
from database.models import User, ExternalDevice
from models import (
    ExternalDeviceCreate,
    ExternalDeviceUpdate,
    ExternalDeviceResponse,
    ExternalDeviceTestResponse,
)
from services import get_agent_url, AGENT_REGISTRY
from core.http_client import get_http_client

router = APIRouter(prefix="/api/external-devices", tags=["External Devices"])

ADB_KEYS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend-data", "adb_keys")
os.makedirs(ADB_KEYS_DIR, exist_ok=True)


def _device_to_response(d: ExternalDevice) -> ExternalDeviceResponse:
    return ExternalDeviceResponse(
        id=d.id,
        uuid=d.uuid,
        name=d.name,
        adb_host=d.adb_host,
        adb_port=d.adb_port,
        agent_id=d.agent_id,
        has_rsa_key=bool(d.rsa_key_path and os.path.exists(d.rsa_key_path)),
        status=d.status,
        resolution=d.resolution,
        created_at=d.created_at,
    )


async def _resolve_agent(agent_id: Optional[str]) -> tuple[str, str]:
    try:
        return get_agent_url(agent_id)
    except HTTPException:
        raise HTTPException(status_code=503, detail="No available Agent")


@router.post("", response_model=ExternalDeviceResponse)
async def create_external_device(
    name: str = Form(...),
    adb_host: str = Form(...),
    adb_port: int = Form(5555),
    agent_id: Optional[str] = Form(None),
    rsa_key_file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    device_uuid = f"ext_{uuid.uuid4().hex[:12]}"
    rsa_key_path = None

    if rsa_key_file:
        key_filename = f"{device_uuid}.key"
        rsa_key_path = os.path.join(ADB_KEYS_DIR, key_filename)
        content = await rsa_key_file.read()
        with open(rsa_key_path, "wb") as f:
            f.write(content)

    if not agent_id and AGENT_REGISTRY:
        agent_id = next(iter(AGENT_REGISTRY))

    device = ExternalDevice(
        uuid=device_uuid,
        user_id=current_user.id,
        agent_id=agent_id,
        name=name,
        adb_host=adb_host,
        adb_port=adb_port,
        rsa_key_path=rsa_key_path,
        status="active",
        resolution="720x1280",
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    return _device_to_response(device)


@router.get("", response_model=list[ExternalDeviceResponse])
async def list_external_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExternalDevice).where(
            ExternalDevice.user_id == current_user.id,
            ExternalDevice.status == "active",
        )
    )
    devices = result.scalars().all()
    return [_device_to_response(d) for d in devices]


@router.put("/{device_uuid}", response_model=ExternalDeviceResponse)
async def update_external_device(
    device_uuid: str,
    update: ExternalDeviceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExternalDevice).where(
            ExternalDevice.uuid == device_uuid,
            ExternalDevice.user_id == current_user.id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="External device not found")

    if update.name is not None:
        device.name = update.name
    if update.adb_host is not None:
        device.adb_host = update.adb_host
    if update.adb_port is not None:
        device.adb_port = update.adb_port
    if update.agent_id is not None:
        device.agent_id = update.agent_id

    await db.commit()
    await db.refresh(device)
    return _device_to_response(device)


@router.delete("/{device_uuid}")
async def delete_external_device(
    device_uuid: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExternalDevice).where(
            ExternalDevice.uuid == device_uuid,
            ExternalDevice.user_id == current_user.id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="External device not found")

    if device.rsa_key_path and os.path.exists(device.rsa_key_path):
        os.remove(device.rsa_key_path)

    await db.delete(device)
    await db.commit()
    return {"success": True, "uuid": device_uuid}


class PairRequest(BaseModel):
    pair_address: str = Field(description="Pairing address host:port (from MIUI wireless debugging)")
    pairing_code: str = Field(description="6-digit pairing code")
    agent_id: Optional[str] = None
    rsa_key_file_id: Optional[int] = None


class PairResponse(BaseModel):
    success: bool
    message: str = ""


@router.post("/pair", response_model=PairResponse)
async def pair_external_device(
    request: PairRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent_url, _ = await _resolve_agent(request.agent_id)

    rsa_key_content = None
    if request.rsa_key_file_id:
        result = await db.execute(
            select(ExternalDevice).where(
                ExternalDevice.id == request.rsa_key_file_id,
                ExternalDevice.user_id == current_user.id,
            )
        )
        device = result.scalar_one_or_none()
        if device and device.rsa_key_path and os.path.exists(device.rsa_key_path):
            with open(device.rsa_key_path, "r") as f:
                rsa_key_content = f.read()

    try:
        resp = await get_http_client().post(
            f"{agent_url}/api/external/pair",
            json={
                "pair_address": request.pair_address,
                "pairing_code": request.pairing_code,
                "rsa_key_content": rsa_key_content,
            },
            timeout=20.0,
        )
        data = resp.json()
        return PairResponse(
            success=data.get("success", False),
            message=data.get("message", ""),
        )
    except httpx.HTTPStatusError as e:
        return PairResponse(success=False, message=f"Agent error: {e.response.text}")
    except Exception as e:
        return PairResponse(success=False, message=f"Pairing failed: {str(e)}")


@router.post("/test-direct", response_model=ExternalDeviceTestResponse)
async def test_direct_connection(
    adb_host: str = Form(...),
    adb_port: int = Form(5555),
    agent_id: Optional[str] = Form(None),
    rsa_key_file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
):
    agent_url, _ = await _resolve_agent(agent_id)
    adb_address = f"{adb_host}:{adb_port}"

    rsa_key_content = None
    if rsa_key_file:
        content = await rsa_key_file.read()
        rsa_key_content = content.decode("utf-8", errors="replace")

    try:
        resp = await get_http_client().post(
            f"{agent_url}/api/external/connect",
            json={
                "adb_address": adb_address,
                "rsa_key_content": rsa_key_content,
            },
            timeout=15.0,
        )
        data = resp.json()
        return ExternalDeviceTestResponse(
            success=data.get("success", False),
            message=data.get("message", ""),
        )
    except httpx.HTTPStatusError as e:
        return ExternalDeviceTestResponse(
            success=False,
            message=f"Agent error: {e.response.text}",
        )
    except Exception as e:
        return ExternalDeviceTestResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


@router.post("/{device_uuid}/test", response_model=ExternalDeviceTestResponse)
async def test_external_device(
    device_uuid: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExternalDevice).where(
            ExternalDevice.uuid == device_uuid,
            ExternalDevice.user_id == current_user.id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="External device not found")

    agent_url, _ = await _resolve_agent(device.agent_id)
    adb_address = f"{device.adb_host}:{device.adb_port}"

    rsa_key_content = None
    if device.rsa_key_path and os.path.exists(device.rsa_key_path):
        with open(device.rsa_key_path, "r") as f:
            rsa_key_content = f.read()

    try:
        resp = await get_http_client().post(
            f"{agent_url}/api/external/connect",
            json={
                "adb_address": adb_address,
                "rsa_key_content": rsa_key_content,
            },
            timeout=15.0,
        )
        data = resp.json()
        return ExternalDeviceTestResponse(
            success=data.get("success", False),
            message=data.get("message", ""),
        )
    except httpx.HTTPStatusError as e:
        return ExternalDeviceTestResponse(
            success=False,
            message=f"Agent error: {e.response.text}",
        )
    except Exception as e:
        return ExternalDeviceTestResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


async def get_external_device_by_uuid(
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
