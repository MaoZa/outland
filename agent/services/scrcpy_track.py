"""
Outland Agent - Scrcpy Media Track (Pure Python Client, v3.x Protocol)

Completely abandon scrcpy CLI client, implement pure Python Scrcpy Client.

Core Process (Four Stages):
  1. Push server JAR and establish ADB TCP tunnel
  2. Launch Java server inside device via app_process
  3. Async TCP Socket handshake (v3.x 13-byte handshake header)
  4. Use PyAV low-level CodecContext to decode H.264 raw stream packet by packet

Technical Notes:
  - control=false: Avoid server requiring dual Socket causing deadlock
  - av.CodecContext.create('h264', 'r'): Low-level API, avoid av.open(pipe) freeze issues
  - 12-byte frame header (8 PTS + 4 Size) + PTS high-bit flag for config packet
  - deque frame buffer queue: recv() pops one frame each time, smooth and non-blocking
  - stop() forcefully cleans up adb forward, prevents port deadlock
"""

import asyncio
import logging
import os
import struct
import time
from collections import deque
from fractions import Fraction
from typing import Optional, Deque

import av
import docker
from av import VideoFrame
from aiortc import MediaStreamTrack


logger = logging.getLogger("ScrcpyTrack")

# ============================================================================
# Environment Configuration
# ============================================================================

# Redroid device address (use container name to access directly in Docker bridge network)
# Priority: environment variable > host.docker.internal > container name > host IP
def _get_redroid_host() -> str:
    """Get Redroid host address"""
    # 1. Environment variable
    env_host = os.environ.get("REDROID_HOST")
    if env_host:
        return env_host
    # 2. host.docker.internal (Docker built-in domain)
    if os.path.exists("/.dockerenv"):
        return "host.docker.internal"
    # 3. Default to container name (in same Docker network)
    return "outland-redroid"

REDROID_HOST: str = _get_redroid_host()
REDROID_ADB_PORT: int = int(os.environ.get("REDROID_ADB_PORT", "5555"))

# Scrcpy server JAR path (host side)
SCRCPY_SERVER_PATH: str = os.environ.get(
    "SCRCPY_SERVER_PATH", "/usr/local/share/scrcpy/scrcpy-server"
)
SCRCPY_SERVER_VERSION: str = "3.3.4"

# ADB TCP forwarding port base (host local port → device abstract socket)
# Each ScrcpyTrack instance gets a unique port starting from this base
SCRCPY_FORWARD_PORT_BASE: int = 27183

_forward_port_counter = 0
_used_forward_ports: set = set()

# Scrcpy video parameters (optimized for low latency)
# Note: Scrcpy defaults to video wallpaper resolution, limited by max_size
# Lower resolution significantly reduces encoding and decoding latency
SCRCPY_MAX_SIZE: int = 720

# FPS setting: 30fps is smooth enough, higher FPS increases encoding overhead
SCRCPY_MAX_FPS: int = 30

# Bitrate setting (unit: bps)
# 2-4Mbps is the optimal range for balancing quality and latency
# Low bitrate reduces encoding latency but degrades quality
# High bitrate has better quality but increases encoding latency
SCRCPY_VIDEO_BITRATE: int = 2_500_000  # 2.5Mbps (reduced from 4Mbps to reduce encoding latency)

# Encoder priority configuration
# hardware: Use device hardware encoder (GPU/dedicated encoder), lowest latency
# software: Use CPU software encoding, better compatibility but slightly higher latency
SCRCPY_ENCODER_TYPE: str = os.environ.get("SCRCPY_ENCODER_TYPE", "hardware")  # Default to hardware encoding

# PTS high bit mask: When PTS MSB is 1, indicates this is a config packet (SPS/PPS)
SCRCPY_PTS_CONFIG_FLAG: int = 1 << 63


# ============================================================================
# Video Quality Levels (for Adaptive Bitrate)
# ============================================================================

class VideoQualityLevel:
    """Video quality level for adaptive bitrate."""

    HIGH = None
    MEDIUM = None
    LOW = None

    def __init__(self, name: str, max_size: int, bitrate: int):
        self.name = name
        self.max_size = max_size
        self.bitrate = bitrate

    @classmethod
    def from_name(cls, name: str) -> "VideoQualityLevel":
        for level in cls.all_levels():
            if level.name == name:
                return level
        return cls.HIGH

    @classmethod
    def all_levels(cls) -> list:
        return [cls.HIGH, cls.MEDIUM, cls.LOW]


VideoQualityLevel.HIGH = VideoQualityLevel("high", 720, 2_500_000)
VideoQualityLevel.MEDIUM = VideoQualityLevel("medium", 480, 1_500_000)
VideoQualityLevel.LOW = VideoQualityLevel("low", 360, 800_000)


class ScrcpyTrack(MediaStreamTrack):
    """
    Pure Python implementation of Scrcpy video track.

    Completely independent of scrcpy CLI, implements Scrcpy v3.x Client protocol in Python,
    decodes H.264 raw stream into VideoFrame consumable by aiortc.

    Attributes:
        container_id: Docker container ID or name
        adb_port: ADB port mapped on host
        kind: Media type, fixed as "video"
    """

    kind = "video"

    def __init__(self, container_id: str, adb_port: int, quality: VideoQualityLevel = None, external_adb_address: Optional[str] = None) -> None:
        """
        Initialize ScrcpyTrack.

        Args:
            container_id: Docker container ID or name
            adb_port: ADB port mapped on host
            quality: Video quality level (default: HIGH)
            external_adb_address: External ADB address (host:port) for non-Docker devices
        """
        super().__init__()

        self.container_id = container_id
        self.adb_port = adb_port
        self._external_adb_address = external_adb_address

        if quality is None:
            quality = VideoQualityLevel.HIGH
        self._quality = quality
        self._max_size = quality.max_size
        self._bitrate = quality.bitrate

        self._container_name: str = self._get_container_name(container_id) if not external_adb_address else container_id

        self._use_localhost_adb: bool = True
        self._forward_port: int = self._allocate_forward_port()
        self._video_codec: str = "h264"  # resolved from scrcpy handshake

        if external_adb_address:
            self._target_device = external_adb_address
            self._use_localhost_adb = False
        elif self._use_localhost_adb:
            self._target_device = f"127.0.0.1:{self.adb_port}"
        else:
            self._target_device = f"{self._container_name}:{self.adb_port}"

        # Phase 2: Scrcpy Java server process
        self._server_process: Optional[asyncio.subprocess.Process] = None

        # Phase 3: Async Socket read/write streams
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

        # Video resolution (from Scrcpy handshake header)
        self._video_width: int = self._max_size
        self._video_height: int = int(self._max_size * 16 / 9)  # Default 16:9

        # Phase 4: PyAV low-level H.264 decoder
        self._codec: Optional[av.CodecContext] = None

        # Frame buffer queue (decoding may produce multiple frames)
        self._frame_queue: Deque[VideoFrame] = deque()

        # Status flags
        self._started: bool = False
        self._stopping: bool = False

        # Statistics
        self._frame_count: int = 0
        self._last_fps_time: float = 0.0
        self._last_fps_count: int = 0

    @staticmethod
    def _allocate_forward_port() -> int:
        global _forward_port_counter
        while True:
            port = SCRCPY_FORWARD_PORT_BASE + _forward_port_counter
            _forward_port_counter += 1
            if port not in _used_forward_ports:
                _used_forward_ports.add(port)
                logger.info("[ScrcpyTrack] Allocated forward port: %d", port)
                return port

    @staticmethod
    def _release_forward_port(port: int) -> None:
        _used_forward_ports.discard(port)
        logger.info("[ScrcpyTrack] Released forward port: %d", port)

    def _get_container_name(self, container_id: str) -> str:
        """
        Get actual container name by container ID.

        Args:
            container_id: Docker container ID or name

        Returns:
            str: Actual container name, used to access in Docker network
        """
        try:
            docker_client = docker.from_env()
            container = docker_client.containers.get(container_id)
            container_name = container.name
            logger.info(f"[ScrcpyTrack] Got container name: {container_name} (ID: {container_id})")
            return container_name
        except Exception as e:
            logger.warning(f"[ScrcpyTrack] Failed to get container name, using container_id: {e}")
            # Fallback: use input container_id
            return container_id

    # ========================================================================
    # Public Interface
    # ========================================================================

    async def _start_scrcpy_async(self) -> None:
        """
        Async complete initialization: push server → establish tunnel → launch server → Socket handshake → init decoder.

        Called by WebRTCManager after creating track.

        Raises:
            RuntimeError: Any phase initialization fails
        """
        try:
            logger.info(f"[ScrcpyTrack] ========== Starting initialization (container: {self.container_id}) ==========")

            await self._phase1_push_and_tunnel()
            await self._phase2_start_server()
            await self._phase3_socket_handshake()
            self._phase4_init_decoder()

            self._started = True
            logger.info("[ScrcpyTrack] ========== Initialization complete, starting streaming ==========")

        except Exception as e:
            logger.error(f"[ScrcpyTrack] Initialization failed: {e}", exc_info=True)
            await self._cleanup()
            raise RuntimeError(f"ScrcpyTrack initialization failed: {e}") from e

    async def recv(self) -> VideoFrame:
        """
        Get next video frame (aiortc calls this method in loop).

        Pops frame from buffer queue; if queue is empty, reads and decodes new data from Socket.

        Returns:
            VideoFrame: Next video frame (yuv420p format)

        Raises:
            StopAsyncIteration: Stream ended or stopping
            RuntimeError: Decoding or reading failed
        """
        if not self._started or self._stopping:
            raise StopAsyncIteration()

        while True:
            # 1. Try to pop decoded frame from queue first
            if self._frame_queue:
                return self._frame_queue.popleft()

            # 2. Queue empty, read next packet from Socket and decode
            try:
                await self._read_and_decode_one_packet()
            except (asyncio.IncompleteReadError, ConnectionResetError, EOFError) as e:
                logger.warning(f"[ScrcpyTrack] Socket connection lost: {e}")
                raise StopAsyncIteration()
            except Exception as e:
                logger.error(f"[ScrcpyTrack] Read/decode failed: {e}", exc_info=True)
                raise RuntimeError(f"Video frame read failed: {e}") from e

    async def stop(self) -> None:
        """
        Stop video stream and cleanup all resources (Socket, server process, ADB tunnel).
        """
        logger.info("[ScrcpyTrack] Stopping...")
        self._stopping = True
        self._started = False
        await self._cleanup()
        await super().stop()
        logger.info("[ScrcpyTrack] Fully stopped")

    # ========================================================================
    # Phase 1: Push server + establish ADB TCP tunnel
    # ========================================================================

    async def _phase1_push_and_tunnel(self) -> None:
        """
        Push scrcpy-server.jar to device and establish ADB forward tunnel.

        Raises:
            RuntimeError: push or forward command execution failed
        """
        # --- 0. Wait for ADB service ready and connect device ---
        # Host network mode uses 127.0.0.1:port, bridge network uses container_name:port
        logger.info(f"[ScrcpyTrack] [Phase 1-0] Waiting for ADB service ready and connecting device...")
        
        max_retries = 30
        retry_delay = 2.0
        device_str = self._target_device  # Use correct target address (127.0.0.1:port or container_name:port)
        
        for attempt in range(max_retries):
            try:
                # First try to connect device
                connect_proc = await asyncio.create_subprocess_exec(
                    "adb", "connect", device_str,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await connect_proc.communicate()
                stdout_str = stdout.decode(errors="replace").strip()
                stderr_str = stderr.decode(errors="replace").strip()
                
                logger.info(f"[ScrcpyTrack] [Phase 1-0] adb connect {device_str}: {stdout_str} {stderr_str}")
                
                # Check if device is connected
                devices_proc = await asyncio.create_subprocess_exec(
                    "adb", "devices",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                devices_stdout, _ = await devices_proc.communicate()
                devices_output = devices_stdout.decode(errors="replace")
                
                logger.info(f"[ScrcpyTrack] [Phase 1-0] Device list:\n{devices_output}")
                
                # Check if device is connected (note: 127.0.0.1:5555 may display as 127.0.0.1:5555)
                if device_str in devices_output and "device" in devices_output:
                    logger.info(f"[ScrcpyTrack] [Phase 1-0] Device {device_str} connected successfully")
                    break
                    
            except Exception as e:
                logger.warning(f"[ScrcpyTrack] [Phase 1-0] Attempt {attempt + 1}/{max_retries} failed: {e}")
            
            if attempt < max_retries - 1:
                logger.info(f"[ScrcpyTrack] [Phase 1-0] Waiting {retry_delay}s before retry...")
                await asyncio.sleep(retry_delay)
        else:
            raise RuntimeError(f"ADB device {device_str} connection timeout (waited {max_retries * retry_delay}s)")
        
        # --- 1.1 Push server JAR ---
        logger.info(f"[ScrcpyTrack] [Phase 1] Pushing scrcpy-server.jar → /data/local/tmp/scrcpy-server.jar")
        push_proc = await asyncio.create_subprocess_exec(
            "adb", "-s", self._target_device,
            "push",
            SCRCPY_SERVER_PATH,
            "/data/local/tmp/scrcpy-server.jar",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await push_proc.communicate()
        if push_proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"adb push failed (code {push_proc.returncode}): {err}")
        logger.info(f"[ScrcpyTrack] [Phase 1] Push successful: {stdout.decode(errors='replace').strip()}")

        # --- 1.2 Establish ADB TCP tunnel ---
        # First cleanup possible old forward, prevent "already forwarded" error
        await asyncio.create_subprocess_exec(
            "adb", "-s", self._target_device,
            "forward", "--remove", f"tcp:{self._forward_port}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        logger.info(f"[ScrcpyTrack] [Phase 1] Establishing tunnel: tcp:{self._forward_port} → localabstract:scrcpy")
        fwd_proc = await asyncio.create_subprocess_exec(
            "adb", "-s", self._target_device,
            "forward",
            f"tcp:{self._forward_port}",
            "localabstract:scrcpy",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await fwd_proc.communicate()
        if fwd_proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"adb forward failed (code {fwd_proc.returncode}): {err}")
        logger.info(f"[ScrcpyTrack] [Phase 1] Tunnel established successfully: {stdout.decode(errors='replace').strip()}")

    # ========================================================================
    # Phase 2: Launch Scrcpy Java server
    # ========================================================================

    async def _phase2_start_server(self) -> None:
        """
        Launch Scrcpy Java server inside device via adb shell + app_process.

        Uses control=false to ensure server only establishes single Socket (video channel),
        avoids server hanging indefinitely (deadlock) due to missing control Socket.

        Raises:
            RuntimeError: Server process startup failed
        """
        logger.info(f"[ScrcpyTrack] [Phase 2] Launching Scrcpy Java server (quality={self._quality.name}, max_size={self._max_size}, bitrate={self._bitrate})...")

        cmd = [
            "adb", "-s", self._target_device,
            "shell",
            f"CLASSPATH=/data/local/tmp/scrcpy-server.jar",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_SERVER_VERSION,
            "tunnel_forward=true",
            "audio=false",
            "control=false",
            "cleanup=false",
            f"video_bit_rate={self._bitrate}",
            f"max_size={self._max_size}",
            f"max_fps={SCRCPY_MAX_FPS}",
        ]

        self._server_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Give server time to initialize and listen on Socket
        # External network devices need more time to start scrcpy-server
        wait_time = 2.5 if self._external_adb_address else 1.0
        await asyncio.sleep(wait_time)

        # Check if process exited unexpectedly
        if self._server_process.returncode is not None:
            try:
                stdout, stderr = await asyncio.wait_for(
                    self._server_process.communicate(), timeout=3.0
                )
                err = stderr.decode(errors="replace").strip()
                out = stdout.decode(errors="replace").strip()
            except asyncio.TimeoutError:
                err, out = "(read timeout)", ""
            raise RuntimeError(
                f"Scrcpy server exited unexpectedly (code {self._server_process.returncode})\n"
                f"stderr: {err}\nstdout: {out}"
            )

        logger.info(f"[ScrcpyTrack] [Phase 2] Server started (PID: {self._server_process.pid})")

    # ========================================================================
    # Phase 3: Async TCP Socket handshake (v3.x 13-byte handshake header)
    # ========================================================================

    async def _phase3_socket_handshake(self) -> None:
        """
        Connect to ADB forward port, read Scrcpy v3.x handshake header.

        Scrcpy v3.3.x handshake protocol format (total 77 bytes):
          - 1 byte:   Dummy byte (0x00)
          - 64 bytes: Device name (UTF-8, null-padded at end)
          - 4 bytes:  Codec ID (ASCII string, e.g., 'h264')
          - 4 bytes:  Width (Big-endian uint32)
          - 4 bytes:  Height (Big-endian uint32)

        With retry mechanism (up to 10 times, 0.5s interval), waiting for server to be ready.

        Raises:
            RuntimeError: Connection or handshake failed
        """
        max_retries = 10
        retry_delay = 0.5

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"[ScrcpyTrack] [Phase 3] Attempting to connect 127.0.0.1:{self._forward_port} "
                    f"({attempt}/{max_retries})..."
                )
                self._reader, self._writer = await asyncio.open_connection(
                    "127.0.0.1", self._forward_port
                )
                logger.info("[ScrcpyTrack] [Phase 3] Socket connection successful!")
                break
            except (ConnectionRefusedError, OSError) as e:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Cannot connect to Scrcpy server "
                        f"(127.0.0.1:{self._forward_port}), retried {max_retries} times: {e}"
                    )
                logger.debug(f"[ScrcpyTrack] [Phase 3] Connection failed, retry in {retry_delay}s: {e}")
                await asyncio.sleep(retry_delay)

        # Read 77-byte handshake header
        # Format: 1 dummy + 64 device_name + 4 codec_id + 4 width (uint32 BE) + 4 height (uint32 BE)
        logger.info("[ScrcpyTrack] [Phase 3] Reading handshake header (77 bytes)...")
        try:
            handshake = await self._reader.readexactly(77)
        except asyncio.IncompleteReadError as e:
            server_stderr = ""
            if self._server_process:
                if self._server_process.returncode is not None:
                    try:
                        _, stderr = await asyncio.wait_for(self._server_process.communicate(), timeout=3.0)
                        server_stderr = stderr.decode(errors="replace").strip()
                    except Exception:
                        server_stderr = "(could not read stderr)"
                    logger.error(
                        "[ScrcpyTrack] [Phase 3] Server exited (code %d) during handshake. stderr: %s",
                        self._server_process.returncode, server_stderr,
                    )
                else:
                    logger.error("[ScrcpyTrack] [Phase 3] Server still running but closed socket (read %d of %d bytes)", len(e.partial), e.expected)
            raise RuntimeError(
                f"Scrcpy server closed socket during handshake (read {len(e.partial)} of {e.expected} bytes)."
                f"{' Server exited: ' + server_stderr if server_stderr else ''}"
            )

        dummy       = handshake[0]
        device_name = handshake[1:65].rstrip(b"\x00").decode("utf-8", errors="replace")
        codec_id    = handshake[65:69].decode("ascii", errors="replace").strip("\x00")
        width       = struct.unpack(">I", handshake[69:73])[0]   # uint32 BE
        height      = struct.unpack(">I", handshake[73:77])[0]   # uint32 BE

        # Save video codec and resolution
        self._video_codec = codec_id
        self._video_width = width
        self._video_height = height

        logger.info(
            f"[ScrcpyTrack] [Phase 3] Handshake complete: "
            f"dummy=0x{dummy:02X}, device='{device_name}', codec='{codec_id}', resolution={width}x{height}"
        )

    # ========================================================================
    # Get video resolution (for frontend coordinate conversion)
    # ========================================================================

    def get_video_resolution(self) -> tuple[int, int]:
        """
        Get actual Scrcpy video resolution.

        Returns:
            tuple[int, int]: (width, height)
        """
        return (self._video_width, self._video_height)

    # ========================================================================
    # Phase 4: Initialize PyAV low-level H.264 decoder
    # ========================================================================

    def _phase4_init_decoder(self) -> None:
        """
        Initialize decoder using the codec reported by scrcpy during handshake.

        Scrcpy v3.x supports: h264, vp8, vp9, av1 (device codec capability dependent).
        """
        codec_name = self._video_codec
        logger.info("[ScrcpyTrack] [Phase 4] Initializing %s decoder...", codec_name)
        self._codec = av.CodecContext.create(codec_name, "r")
        logger.info(f"[ScrcpyTrack] [Phase 4] Decoder ready: {self._codec.name}")

    # ========================================================================
    # recv() core logic: read single Scrcpy packet and decode
    # ========================================================================

    async def _read_and_decode_one_packet(self) -> None:
        """
        Read one Scrcpy v3.x format video packet from Socket and decode.

        Scrcpy v3.x video frame format:
          - 8 bytes: PTS (Big-endian uint64)
              * MSB is 1 (>= 2^63): config packet (SPS/PPS), decode but don't enqueue
              * MSB is 0: normal video frame
          - 4 bytes: data length Size (Big-endian uint32)
          - N bytes: H.264 raw stream data (NALU format)

        Decoded VideoFrame converted to yuv420p and stored in self._frame_queue.
        """
        assert self._reader is not None and self._codec is not None

        # Read 12-byte frame header
        header = await self._reader.readexactly(12)
        pts_raw = struct.unpack(">Q", header[:8])[0]   # uint64 BE
        size    = struct.unpack(">I", header[8:12])[0]  # uint32 BE

        is_config = bool(pts_raw & SCRCPY_PTS_CONFIG_FLAG)
        pts = pts_raw & ~SCRCPY_PTS_CONFIG_FLAG  # Remove MSB flag, get real PTS (microseconds)

        # Read H.264 raw stream data
        data = await self._reader.readexactly(size)

        if is_config:
            logger.debug(f"[ScrcpyTrack] Received config packet (SPS/PPS), size={size}, feeding to decoder")

        # Feed to PyAV parser
        packets = self._codec.parse(data)

        for pkt in packets:
            try:
                frames = self._codec.decode(pkt)
            except Exception as e:
                logger.warning(f"[ScrcpyTrack] Decode failed (skipping packet): {e}")
                continue

            for frame in frames:
                if is_config:
                    # Frames decoded from config packet not enqueued (usually no valid image frame)
                    continue

                # Convert to yuv420p for aiortc encoding
                try:
                    video_frame = self._convert_frame(frame, pts)
                    self._frame_queue.append(video_frame)
                    self._update_fps_stats()
                except Exception as e:
                    logger.warning(f"[ScrcpyTrack] Frame conversion failed (skipping): {e}")

    def _convert_frame(self, frame: av.VideoFrame, pts_us: int) -> VideoFrame:
        """
        Convert PyAV decoded frame to VideoFrame usable by aiortc.

        Args:
            frame: PyAV decoded raw frame
            pts_us: PTS read from Scrcpy frame header (microseconds)

        Returns:
            VideoFrame: yuv420p format, with correct pts and time_base set
        """
        w = frame.width
        h = frame.height
        aligned_w = (w + 15) & ~15
        aligned_h = (h + 15) & ~15
        needs_reformat = (
            aligned_w != w or aligned_h != h
            or frame.format.name not in ("yuv420p", "yuvj420p")
        )
        if needs_reformat:
            frame = frame.reformat(width=aligned_w, height=aligned_h, format="yuv420p")

        if pts_us > 0:
            frame.pts = pts_us * 90 // 1000
        else:
            frame.pts = self._frame_count
        frame.time_base = Fraction(1, 90000)

        return frame

    def _update_fps_stats(self) -> None:
        """
        Update frame count and periodically print FPS statistics.
        """
        self._frame_count += 1

        if self._frame_count == 1:
            logger.info(
                f"[ScrcpyTrack] First frame decoded successfully! Queue length: {len(self._frame_queue)}"
            )
            self._last_fps_time = time.time()
            self._last_fps_count = 1

        if self._frame_count % 30 == 0:
            now = time.time()
            elapsed = now - self._last_fps_time
            if elapsed > 0:
                fps = (self._frame_count - self._last_fps_count) / elapsed
                logger.info(f"[ScrcpyTrack] Frame #{self._frame_count}, real-time FPS: {fps:.1f}")
            self._last_fps_time = now
            self._last_fps_count = self._frame_count

    # ========================================================================
    # Resource Cleanup
    # ========================================================================

    async def _cleanup(self) -> None:
        """
        Cleanup all resources: Socket, server process, ADB forward tunnel.

        Executes in order, ensuring each step's errors don't affect subsequent cleanup.
        """
        # 1. Close Socket
        if self._writer is not None:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
                logger.info("[ScrcpyTrack] Socket closed")
            except Exception as e:
                logger.debug(f"[ScrcpyTrack] Error closing Socket (ignored): {e}")
            finally:
                self._writer = None
                self._reader = None

        # 2. Terminate Scrcpy Java server process
        if self._server_process is not None:
            try:
                if self._server_process.returncode is None:
                    self._server_process.kill()
                    await asyncio.wait_for(self._server_process.wait(), timeout=5.0)
                    logger.info("[ScrcpyTrack] Scrcpy server process terminated")
            except Exception as e:
                logger.debug(f"[ScrcpyTrack] Error terminating server process (ignored): {e}")
            finally:
                self._server_process = None

        # 3. Remove ADB TCP tunnel (prevent port deadlock)
        try:
            logger.info(f"[ScrcpyTrack] Cleaning up ADB forward tcp:{self._forward_port}...")
            rm_proc = await asyncio.create_subprocess_exec(
                "adb", "-s", self._target_device,
                "forward", "--remove", f"tcp:{self._forward_port}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(rm_proc.wait(), timeout=5.0)
            logger.info(f"[ScrcpyTrack] ADB forward tcp:{self._forward_port} removed")
        except Exception as e:
            logger.debug(f"[ScrcpyTrack] Error removing ADB forward (ignored): {e}")

        # 4. Release forward port
        self._release_forward_port(self._forward_port)

        # 5. Cleanup decoder and frame queue
        self._codec = None
        self._frame_queue.clear()

    async def restart_with_quality(self, quality: VideoQualityLevel) -> None:
        """
        Restart Scrcpy with a different quality level.

        This will stop the current stream, update quality settings, and restart
        all phases (server, socket, decoder).

        Args:
            quality: New video quality level to use
        """
        logger.info(f"[ScrcpyTrack] Restarting with quality: {quality.name} (max_size={quality.max_size}, bitrate={quality.bitrate})")

        self._stopping = True
        self._started = False

        await self._cleanup()

        self._quality = quality
        self._max_size = quality.max_size
        self._bitrate = quality.bitrate
        self._video_width = self._max_size
        self._video_height = int(self._max_size * 16 / 9)

        self._server_process = None
        self._reader = None
        self._writer = None
        self._codec = None
        self._frame_queue.clear()

        self._stopping = False

        try:
            logger.info(f"[ScrcpyTrack] ========== Restarting with quality: {quality.name} ==========")
            await self._phase1_push_and_tunnel()
            await self._phase2_start_server()
            await self._phase3_socket_handshake()
            self._phase4_init_decoder()
            self._started = True
            logger.info(f"[ScrcpyTrack] ========== Restart complete, streaming at {quality.name} ==========")
        except Exception as e:
            logger.error(f"[ScrcpyTrack] Restart failed: {e}", exc_info=True)
            await self._cleanup()
            raise RuntimeError(f"ScrcpyTrack restart failed: {e}") from e

    def get_quality(self) -> VideoQualityLevel:
        """Get current video quality level."""
        return self._quality

    def __del__(self) -> None:
        """
        Attempt synchronous cleanup on destruction (fallback, mainly relies on stop() async cleanup).
        """
        try:
            if self._server_process is not None and self._server_process.returncode is None:
                self._server_process.kill()
        except Exception:
            pass
