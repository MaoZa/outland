"""
Outland Backend - Stream Router

提供 WebRTC 流媒体相关的 API 路由。

接口：
- POST /api/stream/webrtc/offer: 处理 WebRTC Offer 并返回 Answer
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.webrtc_manager import get_webrtc_manager


# ============================================================================
# Pydantic Models
# ============================================================================

class WebRTCOfferRequest(BaseModel):
    """
    WebRTC Offer 请求模型
    
    Attributes:
        container_id: Docker 容器 ID
        sdp: SDP Offer 字符串
        type: SDP 类型，通常为 "offer"
    """
    container_id: str
    sdp: str
    type: str = "offer"


class WebRTCAnswerResponse(BaseModel):
    """
    WebRTC Answer 响应模型
    
    Attributes:
        sdp: SDP Answer 字符串
        type: SDP 类型，通常为 "answer"
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
        500: {"description": "WebRTC 连接建立失败"}
    },
    summary="处理 WebRTC Offer",
    description="""
    接收前端发来的 WebRTC SDP Offer，建立 WebRTC 连接并返回 Answer。
    
    此接口会：
    1. 根据 container_id 获取容器的 ADB 端口
    2. 启动 scrcpy 视频捕获
    3. 创建 RTCPeerConnection 并配置 STUN 服务器
    4. 返回 SDP Answer 给前端
    
    前端收到 Answer 后应设置远端描述，然后开始接收视频流。
    
    控制指令通过 DataChannel 发送，格式为 JSON：
    - 点击: {"action": "click", "x": 100, "y": 200}
    - 滑动: {"action": "swipe", "x1": 100, "y1": 200, "x2": 300, "y2": 400, "duration": 300}
    - 输入: {"action": "input", "text": "hello"}
    - 按键: {"action": "keyevent", "keycode": 26}
    """
)
async def handle_webrtc_offer(request: WebRTCOfferRequest) -> WebRTCAnswerResponse:
    """
    处理 WebRTC Offer 并返回 Answer
    
    Args:
        request: WebRTC Offer 请求，包含 container_id 和 SDP
        
    Returns:
        WebRTCAnswerResponse: 包含 SDP Answer
        
    Raises:
        HTTPException: 容器不存在或连接建立失败
    """
    try:
        webrtc_manager = get_webrtc_manager()
        answer = await webrtc_manager.handle_offer(
            container_id=request.container_id,
            sdp=request.sdp,
            offer_type=request.type
        )
        
        return WebRTCAnswerResponse(
            sdp=answer.sdp,
            type=answer.type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"WebRTC 连接建立失败: {str(e)}"
        )
