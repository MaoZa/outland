"""
Outland Agent - WebRTC Manager

Provides WebRTC connection management, handles video streaming and control signaling.

Core Features:
- Manage WebRTC connection collections for each container
- Handle SDP Offer/Answer exchange
- Receive control commands via DataChannel and forward to AdbManager

Technical Notes:
- Use STUN server configuration to get srflx candidates
- Control commands execute concurrently without serial queue (eliminates latency accumulation)
- Video resolution pre-cached from ScrcpyTrack to AdbManager, avoids wm size calls

Deployment Notes:
- Agent must use network_mode: "host" to ensure UDP media streams work properly
- Use Xiaomi and Bilibili STUN servers to solve domestic network NAT traversal issues
"""

import asyncio
import json
import logging
import os
import sys
import traceback as tb_module
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
    MediaStreamTrack,
)
from aiortc.contrib.media import MediaRelay

from fastapi import HTTPException

from services.adb_client import get_adb_manager, AdbManager
from services.scrcpy_track import ScrcpyTrack, VideoQualityLevel


# ============================================================================
# STUN Server Configuration
# ============================================================================

DEFAULT_STUN_SERVERS = [
    "stun:stun.miwifi.com:3478",
    "stun:stun.chat.bilibili.com:3478"
]

def get_stun_servers() -> list[str]:
    """
    Get STUN servers from environment variable or use defaults.

    Environment Variable:
        STUN_SERVERS: comma-separated list of STUN server URLs
                      Example: "stun:stun.example.com:3478,stun:stun2.example.com:3478"

    Returns:
        List of STUN server URLs
    """
    stun_env = os.environ.get("STUN_SERVERS", "")
    if not stun_env:
        return DEFAULT_STUN_SERVERS
    return [s.strip() for s in stun_env.split(",") if s.strip()]


# ============================================================================
# AIORTC / AIOICE Monkey Patch
# ============================================================================
# Fix critical bug where ifaddr fails to get physical network card causing UDP binding failure in Linux Docker
# 
# Root cause:
# The aioice library uses ifaddr.get_adapters() to get local IP, but Docker containers may fail to
# correctly get the physical network card IP (returns empty list), causing UDP Socket binding failure
# and no candidate generation.
#
# Fix:
# Patch aioice.ice.get_host_addresses function, add "0.0.0.0" as fallback when address list is empty
# to allow aiortc to successfully establish UDP Socket binding on all network cards.
import aioice.ice
_original_get_host_addresses = aioice.ice.get_host_addresses

def patched_get_host_addresses(use_ipv4: bool, use_ipv6: bool) -> list[str]:
    """
    Get local IP address list, fix ifaddr failure in Docker containers.
    
    When ifaddr fails to get physical network card IP, add "0.0.0.0" as fallback,
    allowing aiortc to successfully create UDP Socket and generate ICE candidates.
    """
    addresses = _original_get_host_addresses(use_ipv4, use_ipv6)
    # Always add "0.0.0.0" to ensure aiortc can listen on all interfaces
    # This way, even if Docker assigns an internal IP, frontend can connect via STUN/srflx candidate
    if "0.0.0.0" not in addresses:
        addresses.append("0.0.0.0")
    return addresses

aioice.ice.get_host_addresses = patched_get_host_addresses


class WebRTCManager:
    """
    WebRTC connection manager
    
    Manages WebRTC connections with all containers, supports video streaming and control signaling.
    
    Attributes:
        _connections: Records set of RTCPeerConnection for each container_id
        _relay: MediaRelay for multiplexing single video stream to multiple clients
    
    Performance Optimization:
    - Control commands execute concurrently using asyncio.create_task()
    - No serial queue, commands don't wait for previous one to complete
    - Video resolution pre-cached from ScrcpyTrack to AdbManager
    """
    
    def __init__(self) -> None:
        """
        Initialize WebRTC manager
        """
        # connections[container_id] = set of RTCPeerConnection
        self._connections: Dict[str, Set[RTCPeerConnection]] = {}
        # MediaRelay for forwarding single video stream to multiple clients
        self._relay = MediaRelay()
        # Container to ScrcpyTrack mapping (only one source per container)
        self._tracks: Dict[str, MediaStreamTrack] = {}
        # AdbManager instance
        self._adb_manager: Optional[AdbManager] = None
    
    def _get_adb_manager(self) -> AdbManager:
        """
        Get AdbManager instance (lazy loading)
        
        Returns:
            AdbManager: ADB manager instance
        """
        if self._adb_manager is None:
            self._adb_manager = get_adb_manager()
        return self._adb_manager
    
    # =========================================================================
    # Control Command Execution (Concurrent Mode, No Queue)
    # =========================================================================
    
    async def _exec_click(self, adb_manager: AdbManager, container_id: str, data: dict) -> None:
        """Execute click command"""
        try:
            await adb_manager.tap_with_conversion(
                container_id,
                data["x"],
                data["y"],
                data.get("video_width", 720),
                data.get("video_height", 1280)
            )
        except Exception as e:
            logger.error("[WebRTC] click execution failed: %s", e)
    
    async def _exec_swipe(self, adb_manager: AdbManager, container_id: str, data: dict) -> None:
        """Execute swipe command"""
        try:
            await adb_manager.swipe_with_conversion(
                container_id,
                data["x1"],
                data["y1"],
                data["x2"],
                data["y2"],
                data.get("duration", 300),
                data.get("video_width", 720),
                data.get("video_height", 1280)
            )
        except Exception as e:
            logger.error("[WebRTC] swipe execution failed: %s", e)
    
    async def _exec_input(self, adb_manager: AdbManager, container_id: str, data: dict) -> None:
        """Execute text input command"""
        try:
            await adb_manager.input_text(container_id, data["text"])
        except Exception as e:
            logger.error("[WebRTC] input execution failed: %s", e)
    
    async def _exec_keyevent(self, adb_manager: AdbManager, container_id: str, data: dict) -> None:
        """Execute key event command"""
        try:
            await adb_manager.keyevent(container_id, data["keycode"])
        except Exception as e:
            logger.error("[WebRTC] keyevent execution failed: %s", e)
    
    async def _exec_long_press(self, adb_manager: AdbManager, container_id: str, data: dict) -> None:
        """Execute long press command"""
        try:
            await adb_manager.long_press(
                container_id,
                data["x"],
                data["y"],
                data.get("video_width", 720),
                data.get("video_height", 1280)
            )
        except Exception as e:
            logger.error("[WebRTC] long_press execution failed: %s", e)
    
    # =========================================================================
    # SDP Processing
    # =========================================================================
    
    def _add_video_mline_to_sdp(self, sdp: str) -> str:
        """
        Add video m-line to Safari SDP
        
        Safari's Offer may only contain DataChannel (application m-line),
        without video track (m=video). aiortc needs video m-line to negotiate video codec correctly.
        
        This method inserts a standards-compliant video m-line into the SDP,
        so aiortc can correctly create Answer with video track.
        
        Args:
            sdp: Original SDP string
            
        Returns:
            str: SDP string with video m-line added
        """
        lines = sdp.split('\r\n')
        
        # Extract ICE authentication info from original SDP
        ice_ufrag = ""
        ice_pwd = ""
        ice_options = ""
        fingerprint = ""
        
        for line in lines:
            if line.startswith("a=ice-ufrag:"):
                ice_ufrag = line
            elif line.startswith("a=ice-pwd:"):
                ice_pwd = line
            elif line.startswith("a=ice-options:"):
                ice_options = line
            elif line.startswith("a=fingerprint:"):
                fingerprint = line
        
        logger.debug("[WebRTC] Extracted ICE info: ufrag=%s...", ice_ufrag[:30] if ice_ufrag else 'None')
        
        # Video m-line template - must include ICE authentication info
        # Use H264 as video codec (good compatibility)
        # mid uses "1" because mid:0 in original SDP is DataChannel
        # Note: Simplified parameters, let aiortc auto-negotiate codec
        video_mline_parts = [
            "m=video 9 UDP/TLS/RTP/SAVPF 120",
            "c=IN IP4 0.0.0.0",
            "a=mid:1",
            "a=recvonly",
            "a=rtcp-mux",
            "a=rtcp-rsize",
            # H264 basic config, don't specify fmtp parameters, let aiortc auto-negotiate
            "a=rtpmap:120 H264/90000",
        ]
        
        # Add ICE authentication info (copied from original SDP)
        if ice_ufrag:
            video_mline_parts.append(ice_ufrag)
        if ice_pwd:
            video_mline_parts.append(ice_pwd)
        if ice_options:
            video_mline_parts.append(ice_options)
        if fingerprint:
            video_mline_parts.append(fingerprint)
            video_mline_parts.append("a=setup:actpass")  # Safari uses actpass
        
        video_mline = "\r\n".join(video_mline_parts) + "\r\n"
        
        # Insert video m-line before first m= line
        new_lines = []
        inserted = False
        
        for line in lines:
            # Insert video m-line before first m= line
            if not inserted and line.startswith('m='):
                new_lines.append(video_mline)
                inserted = True
            
            new_lines.append(line)
        
        # If no m= line found (insert at beginning)
        if not inserted:
            new_lines.insert(0, video_mline)
        
        result = '\r\n'.join(new_lines)
        logger.debug("[WebRTC] SDP after adding video m-line:\n%s", result[:600])
        return result
    
    def _sanitize_remote_description(self, pc: RTCPeerConnection) -> None:
        """
        Clean incompatible parameters from Safari SDP
        
        Safari's SDP Offer may contain parameters not fully supported by aiortc,
        such as certain rtcp-fb types or fmtp parameters. These parameters cause
        "None is not in list" error during createAnswer.
        
        Solution: Modify the parameter list in pc._remote_description object,
        remove incompatible parameters.
        
        Args:
            pc: RTCPeerConnection instance
        """
        try:
            # Get current remote description
            remote_desc = pc.remoteDescription
            if not remote_desc or not remote_desc.sdp:
                logger.debug("[WebRTC] No remote description, no need to clean")
                return
            
            logger.debug("[WebRTC] Original SDP first 500 chars:\n%s", remote_desc.sdp[:500])
            
            sdp_lines = remote_desc.sdp.split('\r\n')
            cleaned_lines = []
            removed_count = 0
            
            for line in sdp_lines:
                should_remove = False
                
                # Skip rtcp-fb lines containing aiortc unsupported parameters
                if line.startswith('a=rtcp-fb:'):
                    parts = line.split()
                    if len(parts) >= 3:
                        payload_type = parts[1]
                        if payload_type == '*':
                            fb_type = parts[2] if len(parts) > 2 else ""
                        if fb_type in ['goog-remb', 'transport-cc', 'ccm', 'fir']:
                            logger.debug("[WebRTC] Removed Safari-specific rtcp-fb: %s", line)
                            should_remove = True
                            removed_count += 1
                
                # Simplify fmtp parameters
                if line.startswith('a=fmtp:'):
                    parts = line.split()
                    if len(parts) >= 2:
                        payload = parts[1]
                        logger.debug("[WebRTC] Simplified fmtp parameter: %s", line)
                        cleaned_lines.append(f"a=fmtp:{payload}")
                        removed_count += 1
                        continue
                
                if not should_remove:
                    cleaned_lines.append(line)
            
            # If modified, reset remote description
            cleaned_sdp = '\r\n'.join(cleaned_lines)
            if cleaned_sdp != remote_desc.sdp:
                logger.info("[WebRTC] SDP cleaned, removed %d lines, resetting remote description", removed_count)
                pc._remote_description = RTCSessionDescription(
                    sdp=cleaned_sdp,
                    type=remote_desc.type
                )
            else:
                logger.debug("[WebRTC] SDP doesn't need cleaning")
                
        except Exception as e:
            logger.warning("[WebRTC] Error during SDP cleaning (ignored): %s", e)
    
    # =========================================================================
    # WebRTC Connection Handling
    # =========================================================================
    
    async def handle_offer(
        self,
        container_id: str,
        sdp: str,
        offer_type: str = "offer",
        external_adb_address: Optional[str] = None,
        rsa_key_path: Optional[str] = None,
        rsa_key_content: Optional[str] = None,
    ) -> RTCSessionDescription:
        """
        Handle WebRTC Offer and return Answer
        
        Create RTCPeerConnection, configure STUN server (optional), add video track,
        set control signaling channel, and generate SDP Answer.
        
        Args:
            container_id: Docker container ID
            sdp: SDP Offer string
            offer_type: SDP type, default "offer"
            
        Returns:
            RTCSessionDescription: Contains SDP Answer
            
        Raises:
            HTTPException: Connection establishment failed
        """
        pc = None
        try:
            logger.info("[WebRTC] Starting to process Offer, container_id: %s", container_id)
            logger.debug("[WebRTC] SDP Offer type: %s, SDP length: %d", offer_type, len(sdp) if sdp else 0)
            
            # Validate SDP
            if not sdp or not isinstance(sdp, str):
                raise ValueError(f"Invalid SDP: {sdp!r}")
            
            # Get container's ADB port
            adb_manager = self._get_adb_manager()
            logger.debug("[WebRTC] Got AdbManager")
            
            if external_adb_address:
                resolved_key_path = rsa_key_path
                if rsa_key_content and not (rsa_key_path and os.path.exists(rsa_key_path)):
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.key', delete=False, dir='/tmp') as kf:
                        kf.write(rsa_key_content)
                        resolved_key_path = kf.name
                    os.chmod(resolved_key_path, 0o600)
                adb_manager.register_external_device(container_id, external_adb_address, resolved_key_path)
            
            adb_port = adb_manager._get_container_adb_port(container_id)
            logger.debug("[WebRTC] Got ADB port: %d", adb_port)
            
            # Must use domestically accessible STUN servers
            # Optimization: Configure RTCPeerConnection low latency parameters
            stun_servers = get_stun_servers()
            pc = RTCPeerConnection(
                configuration=RTCConfiguration(
                    iceServers=[
                        RTCIceServer(urls=[server]) for server in stun_servers
                    ],
                )
            )
            
            # Initialize connection record
            if container_id not in self._connections:
                self._connections[container_id] = set()
            self._connections[container_id].add(pc)
            
            # Import ScrcpyTrack (lazy import to avoid circular dependency)
            from services.scrcpy_track import ScrcpyTrack
            
            # Create video track (if not already created for this container)
            if container_id not in self._tracks:
                if external_adb_address:
                    await adb_manager.wake_screen(container_id)
                logger.info("[WebRTC] Creating ScrcpyTrack for container %s (ADB port: %d)...", container_id, adb_port)
                track = ScrcpyTrack(container_id, adb_port, external_adb_address=external_adb_address)
                await track._start_scrcpy_async()
                self._tracks[container_id] = track
                
                # Get actual physical screen resolution and cache, avoid subsequent wm size calls
                # Note: Must use get_screen_size() to get physical resolution (e.g., 720x1280),
                # not video resolution (e.g., 408x720), because coordinate conversion needs physical resolution
                screen_w, screen_h = await adb_manager.get_screen_size(container_id)
                adb_manager.set_screen_size(container_id, screen_w, screen_h)
                video_w, video_h = track.get_video_resolution()
                logger.info("[WebRTC] ScrcpyTrack created, physical screen: %dx%d, video stream: %dx%d", 
                           screen_w, screen_h, video_w, video_h)
            
            # Use MediaRelay to multiplex video stream
            source_track = self._tracks[container_id]
            relayed_track = self._relay.subscribe(source_track)
            
            logger.debug("[WebRTC] Source track type: %s, relayed track type: %s", type(source_track).__name__, type(relayed_track).__name__)
            
            # First set up DataChannel handler
            self._setup_datachannel(pc, container_id)
            
            # Also proactively create DataChannel on backend
            logger.info("[WebRTC] Proactively creating 'control' DataChannel...")
            backend_dc = pc.createDataChannel("control", ordered=True)
            self._setup_backend_datachannel(backend_dc, pc, container_id)
            
            # Set up connection close handling
            self._setup_connection_close(pc, container_id)
            
            # Add video track first, then set remote description
            pc.addTrack(relayed_track)
            logger.info("[WebRTC] Added video track to RTCPeerConnection")
            
            # Check if SDP has video m-line
            has_video_mline = "m=video" in sdp.lower()
            logger.debug("[WebRTC] SDP contains video m-line: %s", has_video_mline)
            
            # Process SDP Offer, set remote description
            logger.info("[WebRTC] Setting SDP Offer...")
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            logger.debug("[WebRTC] SDP Offer set")
            
            logger.info("[WebRTC] SDP Offer set, starting to create Answer...")

            # Try to create Answer
            try:
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                logger.info("[WebRTC] SDP Answer created and set as local description")
            except Exception as answer_error:
                logger.warning("[WebRTC] createAnswer failed: %s", answer_error)
                logger.info("[WebRTC] Trying to remove video track and retry...")
                
                for transceiver in pc.getTransceivers():
                    if transceiver.sender and transceiver.sender.track:
                        pc.removeTrack(transceiver.sender)
                        logger.info("[WebRTC] Removed track: %s", transceiver.sender.track.kind)
                
                try:
                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)
                    logger.info("[WebRTC] SDP Answer (no video) created")
                except Exception as retry_error:
                    logger.error("[WebRTC] Retry also failed: %s", retry_error)
                    raise
            
            # Must wait for ICE candidate gathering to complete
            gathering_complete = asyncio.Event()
            
            @pc.on("icegatheringstatechange")
            def on_icegatheringstatechange():
                if pc.iceGatheringState == "complete":
                    gathering_complete.set()
                    
            if pc.iceGatheringState != "complete":
                try:
                    await asyncio.wait_for(gathering_complete.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("[WebRTC] ICE gathering timeout, trying to return existing SDP")
            
            # Validate Answer is valid
            if not pc.localDescription or not pc.localDescription.sdp:
                raise RuntimeError("Created SDP Answer is invalid")
            
            logger.debug("[WebRTC] Answer SDP length: %d", len(pc.localDescription.sdp))
            
            return pc.localDescription
            
        except HTTPException:
            raise
        except ValueError as e:
            logger.error("[WebRTC] SDP parsing error: %s", e)
            await self._cleanup_connection(pc, container_id)
            raise HTTPException(
                status_code=400,
                detail=f"SDP format error: {str(e)}"
            )
        except Exception as e:
            logger.error("[WebRTC] Exception occurred: %s: %s", type(e).__name__, e)
            logger.error("[WebRTC] Full traceback:")
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_tb:
                tb_list = tb_module.extract_tb(exc_tb)
                for frame in tb_list:
                    logger.error("  File '%s', line %d, in %s", frame.filename, frame.lineno, frame.name)
                    logger.error("    %s", frame.line)
            await self._cleanup_connection(pc, container_id)
            raise HTTPException(
                status_code=500,
                detail=f"WebRTC connection establishment failed: {type(e).__name__}: {str(e)}"
            )
    
    def _setup_datachannel(self, pc: RTCPeerConnection, container_id: str) -> None:
        """
        Set up DataChannel handling
        
        Listen to "control" data channel, parse control commands and execute concurrently.
        No longer uses serial queue, commands don't wait for previous one to complete.
        
        Args:
            pc: RTCPeerConnection instance
            container_id: Docker container ID
        """
        adb_manager = self._get_adb_manager()
        
        @pc.on("datachannel")
        def on_datachannel(channel):
            """Handle data channel events"""
            logger.debug("[WebRTC] DataChannel event: label=%s, state=%s", channel.label, channel.readyState)
            
            if channel.label == "control":
                @channel.on("open")
                def on_channel_open():
                    logger.info("[WebRTC] Control DataChannel opened")
                
                @channel.on("close")
                def on_channel_close():
                    logger.debug("[WebRTC] Control DataChannel closed")
                
                @channel.on("error")
                def on_channel_error(err):
                    logger.error("[WebRTC] Control DataChannel error: %s", err)
                
                @channel.on("message")
                def on_message(message):
                    """
                    Handle control commands - execute concurrently, no queuing
                    
                    Message format: {"action": "click", "x": 100, "y": 200}
                    """
                    if message is None:
                        return
                    
                    try:
                        data = json.loads(message)
                        action = data.get("action")
                        
                        # config is synchronous response
                        if action == "config":
                            if container_id in self._tracks:
                                track = self._tracks[container_id]
                                width, height = track.get_video_resolution()
                                if channel.readyState == "open":
                                    channel.send(json.dumps({
                                        "type": "config",
                                        "width": width,
                                        "height": height
                                    }))
                            return
                        
                        # Execute control commands concurrently, no queuing
                        if action == "click":
                            asyncio.create_task(self._exec_click(adb_manager, container_id, data))
                        elif action == "swipe":
                            asyncio.create_task(self._exec_swipe(adb_manager, container_id, data))
                        elif action == "input":
                            asyncio.create_task(self._exec_input(adb_manager, container_id, data))
                        elif action == "keyevent":
                            asyncio.create_task(self._exec_keyevent(adb_manager, container_id, data))
                        elif action == "long_press":
                            asyncio.create_task(self._exec_long_press(adb_manager, container_id, data))
                        
                    except json.JSONDecodeError as e:
                        logger.error("[WebRTC] JSON parsing failed: %s", e)
                    except Exception as e:
                        logger.error("[WebRTC] Exception during message processing: %s", e)

    def _setup_backend_datachannel(self, channel, pc: RTCPeerConnection, container_id: str) -> None:
        """
        Set up handler for backend-initiated DataChannel
        
        Args:
            channel: RTCDataChannel instance
            pc: RTCPeerConnection instance
            container_id: Docker container ID
        """
        adb_manager = self._get_adb_manager()
        
        @channel.on("open")
        def on_channel_open():
            logger.info("[WebRTC] Backend DataChannel opened")
        
        @channel.on("close")
        def on_channel_close():
            logger.debug("[WebRTC] Backend DataChannel closed")
        
        @channel.on("error")
        def on_channel_error(err):
            logger.error("[WebRTC] Backend DataChannel error: %s", err)
        
        @channel.on("message")
        def on_message(message):
            """Handle backend DataChannel messages - execute concurrently"""
            if message is None:
                return
            
            try:
                data = json.loads(message)
                action = data.get("action")
                
                # config is synchronous response
                if action == "config":
                    if container_id in self._tracks:
                        track = self._tracks[container_id]
                        width, height = track.get_video_resolution()
                        if channel.readyState == "open":
                            channel.send(json.dumps({
                                "type": "config",
                                "width": width,
                                "height": height
                            }))
                    return
                
                # Execute concurrently
                if action == "click":
                    asyncio.create_task(self._exec_click(adb_manager, container_id, data))
                elif action == "swipe":
                    asyncio.create_task(self._exec_swipe(adb_manager, container_id, data))
                elif action == "input":
                    asyncio.create_task(self._exec_input(adb_manager, container_id, data))
                elif action == "keyevent":
                    asyncio.create_task(self._exec_keyevent(adb_manager, container_id, data))
                elif action == "long_press":
                    asyncio.create_task(self._exec_long_press(adb_manager, container_id, data))
                    
            except json.JSONDecodeError as e:
                logger.error("[WebRTC] JSON parsing failed: %s", e)
            except Exception as e:
                logger.error("[WebRTC] Exception during message processing: %s", e)

    def _setup_connection_close(self, pc: RTCPeerConnection, container_id: str) -> None:
        """
        Set up connection close handling
        
        Args:
            pc: RTCPeerConnection instance
            container_id: Docker container ID
        """
        @pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            if pc.iceConnectionState == "closed" or pc.iceConnectionState == "failed":
                await self._cleanup_connection(pc, container_id)
    
    async def _cleanup_connection(self, pc: Optional[RTCPeerConnection], container_id: str) -> None:
        """
        Cleanup connection resources
        
        Args:
            pc: RTCPeerConnection instance
            container_id: Docker container ID
        """
        if pc is None:
            return
        
        if container_id in self._connections:
            self._connections[container_id].discard(pc)
            if not self._connections[container_id]:
                del self._connections[container_id]
        
        if container_id not in self._connections:
            if container_id in self._tracks:
                try:
                    await self._tracks[container_id].stop()
                except Exception:
                    pass
                del self._tracks[container_id]
        
        try:
            await pc.close()
        except Exception:
            pass

    async def change_quality(self, container_id: str, quality_name: str) -> dict:
        """
        Change video quality for an existing container's stream.

        This will restart the ScrcpyTrack with the new quality settings,
        effectively reinitializing the video stream.

        Args:
            container_id: Docker container ID
            quality_name: Quality level name ("high", "medium", "low")

        Returns:
            dict: Contains success status and new quality info

        Raises:
            HTTPException: If container or quality not found
        """
        quality = VideoQualityLevel.from_name(quality_name)

        if container_id not in self._tracks:
            raise HTTPException(status_code=404, detail=f"No track found for container {container_id}")

        track = self._tracks[container_id]
        old_quality = track.get_quality()

        logger.info("[WebRTC] Changing quality for container %s: %s -> %s",
                     container_id, old_quality.name, quality.name)

        await track.restart_with_quality(quality)

        return {
            "success": True,
            "container_id": container_id,
            "old_quality": old_quality.name,
            "new_quality": quality.name,
            "max_size": quality.max_size,
            "bitrate": quality.bitrate
        }

    async def get_connection_stats(self, container_id: str) -> dict:
        """
        Get WebRTC connection statistics for monitoring.

        Args:
            container_id: Docker container ID

        Returns:
            dict: Connection statistics including bandwidth estimates
        """
        if container_id not in self._connections or not self._connections[container_id]:
            return {"status": "no_connection"}

        pc = next(iter(self._connections[container_id]))

        try:
            stats = await pc.getStats()
            for report in stats.values():
                if report.type == "candidate-pair" and report.get("state") == "succeeded":
                    return {
                        "status": "connected",
                        "available_outgoing_bitrate": report.get("availableOutgoingBitrate", 0),
                        "packets_lost": report.get("packetsLost", 0),
                        "round_trip_time": report.get("currentRoundTripTime", 0),
                        "bytes_sent": report.get("bytesSent", 0),
                        "remote_timestamp": report.get("remoteTimestamp", 0)
                    }
            return {"status": "no_active_candidate_pair"}
        except Exception as e:
            logger.warning("[WebRTC] Failed to get connection stats: %s", e)
            return {"status": "error", "error": str(e)}

    async def close_all(self) -> None:
        """
        Close all WebRTC connections
        """
        for container_id in list(self._connections.keys()):
            for pc in list(self._connections[container_id]):
                await self._cleanup_connection(pc, container_id)
        
        for container_id in list(self._tracks.keys()):
            if container_id not in self._connections or not self._connections[container_id]:
                try:
                    await self._tracks[container_id].stop()
                except Exception:
                    pass
        self._tracks.clear()


# ============================================================================
# Global Instance Accessor Function
# ============================================================================

_webrtc_manager: Optional[WebRTCManager] = None


def get_webrtc_manager() -> WebRTCManager:
    """
    Get WebRTCManager global singleton instance
    
    Returns:
        WebRTCManager: WebRTC manager instance
    """
    global _webrtc_manager
    if _webrtc_manager is None:
        _webrtc_manager = WebRTCManager()
    return _webrtc_manager


async def shutdown_webrtc_manager() -> None:
    """
    Shutdown WebRTC manager
    """
    global _webrtc_manager
    if _webrtc_manager is not None:
        await _webrtc_manager.close_all()
        _webrtc_manager = None
