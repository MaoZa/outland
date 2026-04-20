"""
Outland Backend - Stream Router

提供 WebRTC 流媒体相关的 API 路由。

接口：
- POST /api/stream/webrtc/offer: 处理 WebRTC Offer 并返回 Answer
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import os
import httpx

# ============================================================================
# Pydantic Models
# ============================================================================

class WebRTCOfferRequest(BaseModel):
    """
    WebRTC Offer 请求模型
    """
    container_id: str
    sdp: str
    type: str = "offer"

class WebRTCAnswerResponse(BaseModel):
    """
    WebRTC Answer 响应模型
    """
    sdp: str
    type: str

# ============================================================================
# Router
# ============================================================================

router = APIRouter()


@router.post(
    "/webrtc/offer",
    response_model=WebRTCAnswerResponse,
    responses={
        404: {"description": "容器不存在"},
        500: {"description": "WebRTC 连接建立失败"},
        502: {"description": "无法连接远程 Agent"}
    },
    summary="代理 WebRTC Offer",
    description="将前端发来的 WebRTC SDP Offer 透明转发给对应容器所属的 Agent。"
)
async def handle_webrtc_offer(request: WebRTCOfferRequest) -> WebRTCAnswerResponse:
    agent_url = os.environ.get("AGENT_URL")
    if not agent_url:
        raise HTTPException(status_code=500, detail="未配置 AGENT_URL 环境变量，网关无法转发请求")
        
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{agent_url}/api/stream/webrtc/offer",
                json=request.model_dump()
            )
            
            # 如果 Agent 返回 404/500 等错误，抛出同样的错误
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
                
            data = resp.json()
            return WebRTCAnswerResponse(**data)
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接到远端 Agent ({agent_url}): {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"代理 WebRTC 请求时发生未知错误: {str(e)}"
        )
