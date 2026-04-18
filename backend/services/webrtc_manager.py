"""
Outland Backend - WebRTC Manager

提供 WebRTC 连接管理，处理视频推流和控制信令。

核心功能：
- 管理每个容器的 WebRTC 连接集合
- 处理 SDP Offer/Answer 交换
- 通过 DataChannel 接收控制指令并转发到 AdbManager

技术要点：
- 使用 STUN 服务器配置解决公网 NAT 穿透问题
- DataChannel 回调中使用 asyncio.create_task() 调用异步 AdbManager 方法
- 一个容器可被多个客户端同时观看

部署说明：
- Docker 部署建议使用 network_mode: "host" 以确保 UDP 媒体流顺利打通
- 或在 NAS 路由器上配置 DMZ/UPnP
"""

import asyncio
import json
from typing import Dict, Set, Optional

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
    MediaStreamTrack,
)
from aiortc.contrib.media import MediaRelay

from fastapi import HTTPException

from backend.services.adb_client import get_adb_manager, AdbManager


class WebRTCManager:
    """
    WebRTC 连接管理器
    
    负责管理与所有容器的 WebRTC 连接，支持视频推流和控制信令。
    
    Attributes:
        _connections: 记录每个 container_id 对应的 RTCPeerConnection 集合
        _relay: MediaRelay 用于复用视频流到多个客户端
    """
    
    def __init__(self) -> None:
        """
        初始化 WebRTC 管理器
        """
        # connections[container_id] = set of RTCPeerConnection
        self._connections: Dict[str, Set[RTCPeerConnection]] = {}
        # MediaRelay 用于将单个视频流转发给多个客户端
        self._relay = MediaRelay()
        # 容器到 ScrcpyTrack 的映射（每个容器只有一个源）
        self._tracks: Dict[str, MediaStreamTrack] = {}
        # AdbManager 实例
        self._adb_manager: Optional[AdbManager] = None
    
    def _get_adb_manager(self) -> AdbManager:
        """
        获取 AdbManager 实例（懒加载）
        
        Returns:
            AdbManager: ADB 管理器实例
        """
        if self._adb_manager is None:
            self._adb_manager = get_adb_manager()
        return self._adb_manager
    
    async def handle_offer(
        self,
        container_id: str,
        sdp: str,
        offer_type: str = "offer"
    ) -> RTCSessionDescription:
        """
        处理 WebRTC Offer 并返回 Answer
        
        创建 RTCPeerConnection，配置 STUN 服务器，添加视频轨道，
        设置控制信令通道，并生成 SDP Answer。
        
        Args:
            container_id: Docker 容器 ID
            sdp: SDP Offer 字符串
            offer_type: SDP 类型，默认 "offer"
            
        Returns:
            RTCSessionDescription: 包含 SDP Answer
            
        Raises:
            HTTPException: 连接建立失败
        """
        pc = None
        try:
            print(f"[WebRTC] 开始处理 Offer，container_id: {container_id}")
            
            # 获取容器的 ADB 端口
            adb_manager = self._get_adb_manager()
            print(f"[WebRTC] 获取到 AdbManager")
            
            adb_port = adb_manager._get_container_adb_port(container_id)
            print(f"[WebRTC] 获取到 ADB 端口: {adb_port}")
            
            
            # 创建 RTCPeerConnection
            # 本地部署不需要 STUN 服务器
            # 如需公网部署，可在此添加 iceServers 配置
            pc = RTCPeerConnection()
            
            # 初始化连接记录
            if container_id not in self._connections:
                self._connections[container_id] = set()
            self._connections[container_id].add(pc)
            
            # 导入 ScrcpyTrack（延迟导入避免循环依赖）
            from backend.services.scrcpy_track import ScrcpyTrack
            
            # 创建视频轨道（如果还没有为这个容器创建）
            if container_id not in self._tracks:
                print(f"[WebRTC] 正在为容器 {container_id} 创建 ScrcpyTrack (ADB端口: {adb_port})...")
                # 创建 ScrcpyTrack 实例并异步启动 scrcpy
                track = ScrcpyTrack(container_id, adb_port)
                await track._start_scrcpy_async()
                self._tracks[container_id] = track
                print(f"[WebRTC] ScrcpyTrack 创建成功")
            
            # 使用 MediaRelay 复用视频流
            # 这样多个客户端可以观看同一个容器的视频
            relayed_track = self._relay.subscribe(self._tracks[container_id])
            
            # 添加视频轨道到连接
            pc.addTrack(relayed_track)
            
            # 设置 DataChannel 处理
            await self._setup_datachannel(pc, container_id)
            
            # 设置连接关闭处理
            self._setup_connection_close(pc, container_id)
            
            # 处理 SDP Offer
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            
            # 创建 SDP Answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            
            # 直接返回 answer，而不是 pc.localDescription
            # 避免 aiortc 内部序列化时可能出现的问题
            return answer
            
        except Exception as e:
            import traceback
            print(f"[WebRTC] 发生异常: {e}")
            print(f"[WebRTC] 完整 traceback:")
            traceback.print_exc()
            # 清理失败的连接
            await self._cleanup_connection(pc, container_id)
            raise HTTPException(
                status_code=500,
                detail=f"WebRTC 连接建立失败: {str(e)}"
            )
    
    async def _setup_datachannel(self, pc: RTCPeerConnection, container_id: str) -> None:
        """
        设置 DataChannel 处理
        
        监听 "control" 数据通道，解析控制指令并转发到 AdbManager。
        
        关键：使用 asyncio.create_task() 调用异步 AdbManager 方法，
        因为 DataChannel 的 on("message") 回调是同步函数。
        
        Args:
            pc: RTCPeerConnection 实例
            container_id: Docker 容器 ID
        """
        adb_manager = self._get_adb_manager()
        
        @pc.on("datachannel")
        def on_datachannel(channel):
            """处理数据通道事件"""
            if channel.label == "control":
                # 监听控制消息
                @channel.on("message")
                def on_message(message):
                    """
                    处理控制指令
                    
                    消息格式：{"action": "click", "x": 100, "y": 200}
                    支持的动作：
                    - click/tap: 点击屏幕 {"action": "click", "x": int, "y": int}
                    - swipe: 滑动屏幕 {"action": "swipe", "x1": int, "y1": int, "x2": int, "y2": int, "duration": int}
                    - input: 文本输入 {"action": "input", "text": str}
                    - keyevent: 按键事件 {"action": "keyevent", "keycode": int}
                    """
                    if message is None:
                        return
                    
                    try:
                        data = json.loads(message)
                        action = data.get("action")
                        
                        # 关键：使用 asyncio.create_task() 调度异步任务
                        # 不能直接 await，否则会阻塞事件循环
                        if action == "click":
                            asyncio.create_task(
                                adb_manager.tap(container_id, data["x"], data["y"])
                            )
                        elif action == "swipe":
                            asyncio.create_task(
                                adb_manager.swipe(
                                    container_id,
                                    data["x1"],
                                    data["y1"],
                                    data["x2"],
                                    data["y2"],
                                    data.get("duration", 300)
                                )
                            )
                        elif action == "input":
                            asyncio.create_task(
                                adb_manager.input_text(container_id, data["text"])
                            )
                        elif action == "keyevent":
                            asyncio.create_task(
                                adb_manager.keyevent(container_id, data["keycode"])
                            )
                    except json.JSONDecodeError:
                        pass  # 忽略无效的 JSON
                    except KeyError as e:
                        # 缺少必要的参数
                        pass
    
    def _setup_connection_close(self, pc: RTCPeerConnection, container_id: str) -> None:
        """
        设置连接关闭处理
        
        当连接关闭时，自动清理连接记录。
        
        Args:
            pc: RTCPeerConnection 实例
            container_id: Docker 容器 ID
        """
        @pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            """监听 ICE 连接状态变化"""
            if pc.iceConnectionState == "closed" or pc.iceConnectionState == "failed":
                await self._cleanup_connection(pc, container_id)
    
    async def _cleanup_connection(self, pc: Optional[RTCPeerConnection], container_id: str) -> None:
        """
        清理连接资源
        
        Args:
            pc: RTCPeerConnection 实例
            container_id: Docker 容器 ID
        """
        if pc is None:
            return
        
        # 从连接记录中移除
        if container_id in self._connections:
            self._connections[container_id].discard(pc)
            if not self._connections[container_id]:
                del self._connections[container_id]
        
        # 如果这个容器没有更多连接，停止视频轨道
        if container_id not in self._connections:
            if container_id in self._tracks:
                try:
                    await self._tracks[container_id].stop()
                except Exception:
                    pass
                del self._tracks[container_id]
        
        # 关闭 RTCPeerConnection
        try:
            await pc.close()
        except Exception:
            pass
    
    async def close_all(self) -> None:
        """
        关闭所有 WebRTC 连接
        
        在应用关闭时调用，确保所有资源被正确释放。
        """
        for container_id in list(self._connections.keys()):
            for pc in list(self._connections[container_id]):
                await self._cleanup_connection(pc, container_id)
        
        # 停止所有视频轨道
        for container_id in list(self._tracks.keys()):
            if container_id not in self._connections or not self._connections[container_id]:
                try:
                    await self._tracks[container_id].stop()
                except Exception:
                    pass
        self._tracks.clear()


# ============================================================================
# 全局实例获取函数
# ============================================================================

_webrtc_manager: Optional[WebRTCManager] = None


def get_webrtc_manager() -> WebRTCManager:
    """
    获取 WebRTCManager 全局单例实例
    
    Returns:
        WebRTCManager: WebRTC 管理器实例
    """
    global _webrtc_manager
    if _webrtc_manager is None:
        _webrtc_manager = WebRTCManager()
    return _webrtc_manager


async def shutdown_webrtc_manager() -> None:
    """
    关闭 WebRTC 管理器
    
    在应用关闭时调用。
    """
    global _webrtc_manager
    if _webrtc_manager is not None:
        await _webrtc_manager.close_all()
        _webrtc_manager = None
