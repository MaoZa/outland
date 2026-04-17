"""
Outland Backend - Automation Router

提供安卓容器自动化控制 API。
支持点击、滑动、文本输入、按键事件等操作。
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.services.adb_client import get_adb_manager


# ============================================================================
# Pydantic Request Models
# ============================================================================

class ClickRequest(BaseModel):
    """点击操作请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    x: Annotated[int, Field(description="点击的 X 坐标", ge=0)]
    y: Annotated[int, Field(description="点击的 Y 坐标", ge=0)]


class SwipeRequest(BaseModel):
    """滑动操作请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    x1: Annotated[int, Field(description="起始 X 坐标", ge=0)]
    y1: Annotated[int, Field(description="起始 Y 坐标", ge=0)]
    x2: Annotated[int, Field(description="结束 X 坐标", ge=0)]
    y2: Annotated[int, Field(description="结束 Y 坐标", ge=0)]
    duration: Annotated[int, Field(description="滑动持续时间（毫秒）", ge=0, default=300)]


class TextRequest(BaseModel):
    """文本输入请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    text: Annotated[str, Field(description="要输入的文本内容")]


class KeyEventRequest(BaseModel):
    """按键事件请求模型"""
    container_id: Annotated[str, Field(description="Docker 容器 ID 或名称", min_length=1)]
    keycode: Annotated[int, Field(description="Android 按键码（如 26=POWER, 4=BACK, 3=HOME）")]


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
# API Endpoints
# ============================================================================

@router.post(
    "/click",
    response_model=ActionResponse,
    responses={
        404: {"description": "容器不存在"},
        500: {"description": "ADB 操作失败"},
        504: {"description": "ADB 连接超时"},
    },
    summary="执行屏幕点击",
    description="在指定容器的屏幕上执行点击操作"
)
async def click(request: ClickRequest) -> ActionResponse:
    """
    执行屏幕点击操作
    
    Args:
        request: 点击请求参数
        
    Returns:
        ActionResponse: 操作成功响应
    """
    try:
        adb = get_adb_manager()
        await adb.tap(request.container_id, request.x, request.y)
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="click",
            detail=f"点击坐标 ({request.x}, {request.y})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"点击操作失败: {str(e)}"
        )


@router.post(
    "/swipe",
    response_model=ActionResponse,
    responses={
        404: {"description": "容器不存在"},
        500: {"description": "ADB 操作失败"},
        504: {"description": "ADB 连接超时"},
    },
    summary="执行屏幕滑动",
    description="在指定容器的屏幕上执行滑动操作"
)
async def swipe(request: SwipeRequest) -> ActionResponse:
    """
    执行屏幕滑动操作
    
    Args:
        request: 滑动请求参数
        
    Returns:
        ActionResponse: 操作成功响应
    """
    try:
        adb = get_adb_manager()
        await adb.swipe(
            request.container_id,
            request.x1, request.y1,
            request.x2, request.y2,
            request.duration
        )
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="swipe",
            detail=f"滑动 ({request.x1}, {request.y1}) → ({request.x2}, {request.y2}), 耗时 {request.duration}ms"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"滑动操作失败: {str(e)}"
        )


@router.post(
    "/text",
    response_model=ActionResponse,
    responses={
        404: {"description": "容器不存在"},
        500: {"description": "ADB 操作失败"},
        504: {"description": "ADB 连接超时"},
    },
    summary="执行文本输入",
    description="在指定容器的屏幕上执行文本输入操作"
)
async def text(request: TextRequest) -> ActionResponse:
    """
    执行文本输入操作
    
    Args:
        request: 文本输入请求参数
        
    Returns:
        ActionResponse: 操作成功响应
    """
    try:
        adb = get_adb_manager()
        await adb.input_text(request.container_id, request.text)
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="text",
            detail=f"输入文本: {request.text[:50]}{'...' if len(request.text) > 50 else ''}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文本输入失败: {str(e)}"
        )


@router.post(
    "/keyevent",
    response_model=ActionResponse,
    responses={
        404: {"description": "容器不存在"},
        500: {"description": "ADB 操作失败"},
        504: {"description": "ADB 连接超时"},
    },
    summary="执行按键事件",
    description="在指定容器上执行按键事件（如 POWER、BACK、HOME）"
)
async def keyevent(request: KeyEventRequest) -> ActionResponse:
    """
    执行按键事件
    
    Args:
        request: 按键事件请求参数
        
    Returns:
        ActionResponse: 操作成功响应
    """
    try:
        adb = get_adb_manager()
        await adb.keyevent(request.container_id, request.keycode)
        
        # 常用按键码名称映射
        keycode_names = {
            3: "HOME",
            4: "BACK",
            5: "CALL",
            6: "ENDCALL",
            26: "POWER",
            27: "CAMERA",
            66: "ENTER",
            67: "DEL",
        }
        key_name = keycode_names.get(request.keycode, f"KEYCODE_{request.keycode}")
        
        return ActionResponse(
            success=True,
            container_id=request.container_id,
            action="keyevent",
            detail=f"按键事件: {key_name} ({request.keycode})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"按键事件失败: {str(e)}"
        )
