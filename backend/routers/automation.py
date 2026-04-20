"""
Outland Backend - Automation Router

提供安卓容器自动化控制 API。
支持点击、滑动、文本输入、按键事件等操作。
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

import os
import httpx

# ============================================================================
# Pydantic Request Models
# ============================================================================

class ClickRequest(BaseModel):
    """点击操作请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID", min_length=1)]
    x: Annotated[int, Field(description="点击的 X 坐标", ge=0)]
    y: Annotated[int, Field(description="点击的 Y 坐标", ge=0)]

class SwipeRequest(BaseModel):
    """滑动操作请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID", min_length=1)]
    x1: Annotated[int, Field(description="起始 X 坐标", ge=0)]
    y1: Annotated[int, Field(description="起始 Y 坐标", ge=0)]
    x2: Annotated[int, Field(description="结束 X 坐标", ge=0)]
    y2: Annotated[int, Field(description="结束 Y 坐标", ge=0)]
    duration: Annotated[int, Field(description="滑动持续时间", ge=0, default=300)]

class TextRequest(BaseModel):
    """文本输入请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID", min_length=1)]
    text: Annotated[str, Field(description="要输入的文本内容")]

class KeyEventRequest(BaseModel):
    """按键事件请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID", min_length=1)]
    keycode: Annotated[int, Field(description="Android 按键码")]

class ActionResponse(BaseModel):
    """操作成功响应模型"""
    success: bool = True
    container_id: str
    action: str
    detail: str = ""

# ============================================================================
# Router Definition
# ============================================================================

router = APIRouter()


# ============================================================================
# Helper
# ============================================================================

async def proxy_to_agent(endpoint: str, payload: dict) -> ActionResponse:
    """透明代理请求到远端 Agent"""
    agent_url = os.environ.get("AGENT_URL")
    if not agent_url:
        raise HTTPException(status_code=500, detail="未配置 AGENT_URL，网关无法转发操作指令")
        
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{agent_url}{endpoint}",
                json=payload
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
                
            return ActionResponse(**resp.json())
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接到远端 Agent ({agent_url}): {str(e)}"
        )


# ============================================================================
# API Endpoints
# ============================================================================

@router.post(
    "/click",
    response_model=ActionResponse,
    summary="代理屏幕点击",
    description="将点击指令透明转发给对应的 Agent"
)
async def click(request: ClickRequest) -> ActionResponse:
    return await proxy_to_agent("/api/action/click", request.model_dump())


@router.post(
    "/swipe",
    response_model=ActionResponse,
    summary="代理屏幕滑动",
    description="将滑动指令透明转发给对应的 Agent"
)
async def swipe(request: SwipeRequest) -> ActionResponse:
    return await proxy_to_agent("/api/action/swipe", request.model_dump())


@router.post(
    "/text",
    response_model=ActionResponse,
    summary="代理文本输入",
    description="将文本输入指令透明转发给对应的 Agent"
)
async def text(request: TextRequest) -> ActionResponse:
    return await proxy_to_agent("/api/action/text", request.model_dump())


@router.post(
    "/keyevent",
    response_model=ActionResponse,
    summary="代理按键事件",
    description="将按键事件透明转发给对应的 Agent"
)
async def keyevent(request: KeyEventRequest) -> ActionResponse:
    return await proxy_to_agent("/api/action/keyevent", request.model_dump())

