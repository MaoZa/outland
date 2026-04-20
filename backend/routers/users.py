from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_db
from database.models import User, Quota, Container
from auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserResponse(BaseModel):
    id: int
    email: str
    is_admin: bool
    is_active: bool
    is_verified: bool

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    is_verified: bool | None = None


class QuotaResponse(BaseModel):
    max_containers: int

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.get("/me/quota", response_model=QuotaResponse)
async def get_my_quota(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Quota).where(Quota.user_id == current_user.id))
    quota = result.scalar_one_or_none()
    if not quota:
        quota = Quota(user_id=current_user.id, max_containers=3)
        db.add(quota)
        await db.commit()
        await db.refresh(quota)
    return QuotaResponse.model_validate(quota)


@router.get("/admin/users", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.put("/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if update.is_active is not None:
        user.is_active = update.is_active
    if update.is_admin is not None:
        user.is_admin = update.is_admin
    if update.is_verified is not None:
        user.is_verified = update.is_verified

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()


@router.put("/admin/users/{user_id}/quota", response_model=QuotaResponse)
async def update_quota(
    user_id: int,
    quota_update: QuotaResponse,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(select(Quota).where(Quota.user_id == user_id))
    quota = result.scalar_one_or_none()

    if quota:
        quota.max_containers = quota_update.max_containers
    else:
        quota = Quota(user_id=user_id, max_containers=quota_update.max_containers)
        db.add(quota)

    await db.commit()
    await db.refresh(quota)
    return QuotaResponse.model_validate(quota)


@router.get("/admin/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    users_count_result = await db.execute(select(User))
    users_count = len(users_count_result.scalars().all())

    containers_result = await db.execute(select(Container))
    containers_count = len(containers_result.scalars().all())

    return {
        "total_users": users_count,
        "total_containers": containers_count,
    }


@router.get("/admin/containers")
async def get_all_containers(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    result = await db.execute(select(Container))
    containers = result.scalars().all()
    return [
        {
            "id": c.id,
            "uuid": c.uuid,
            "user_id": c.user_id,
            "agent_id": c.agent_id,
            "container_id": c.container_id,
            "status": c.status,
            "resolution": c.resolution,
        }
        for c in containers
    ]
