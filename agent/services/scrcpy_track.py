"""
Outland Agent - Scrcpy Media Track (Pure Python Client, v3.x Protocol)

彻底抛弃 scrcpy CLI 客户端，改为在 Python 中手写纯正的 Scrcpy Client。

核心流程（四阶段）：
  1. 推送服务端 JAR 并建立 ADB TCP 隧道
  2. 通过 app_process 拉起设备内的 Java 服务端
  3. 异步 TCP Socket 握手（v3.x 13 字节握手头）
  4. 使用 PyAV 底层 CodecContext 逐包解码 H.264 裸流

技术要点：
  - control=false：避免服务端要求双 Socket 导致死锁
  - av.CodecContext.create('h264', 'r')：底层 API，杜绝 av.open(pipe) 卡死问题
  - 12 字节帧头（8 PTS + 4 Size）+ PTS 高位标识配置包
  - deque 帧缓冲队列：recv() 每次弹出一帧，流畅无阻塞
  - stop() 时强制清理 adb forward，防止端口死锁
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
from av import VideoFrame
from aiortc import MediaStreamTrack


logger = logging.getLogger("ScrcpyTrack")

# ============================================================================
# 环境配置
# ============================================================================

# Redroid 设备地址（使用 ADB 端口映射）
REDROID_HOST: str = os.environ.get("REDROID_HOST", "127.0.0.1")
REDROID_ADB_PORT: int = int(os.environ.get("REDROID_ADB_PORT", "5555"))

# Scrcpy 服务端 JAR 路径（宿主机侧）
SCRCPY_SERVER_PATH: str = os.environ.get(
    "SCRCPY_SERVER_PATH", "/usr/local/share/scrcpy/scrcpy-server"
)
SCRCPY_SERVER_VERSION: str = "3.3.4"

# ADB TCP 转发端口（宿主机本地端口 → 设备 abstract socket）
SCRCPY_FORWARD_PORT: int = 27183

# Scrcpy 视频参数
SCRCPY_MAX_SIZE: int = 720
SCRCPY_MAX_FPS: int = 30
SCRCPY_VIDEO_BITRATE: int = 2_000_000

# PTS 高位掩码：当 PTS 最高位为 1 时，表示这是一个配置包（SPS/PPS）
SCRCPY_PTS_CONFIG_FLAG: int = 1 << 63


class ScrcpyTrack(MediaStreamTrack):
    """
    纯 Python 实现的 Scrcpy 视频轨道。

    完全不依赖 scrcpy CLI，通过 Python 手写 Scrcpy v3.x Client 协议，
    将 H.264 裸流解码为 aiortc 可消费的 VideoFrame。

    Attributes:
        container_id: Docker 容器 ID 或名称
        adb_port: 宿主机上映射的 ADB 端口
        kind: 媒体类型，固定为 "video"
    """

    kind = "video"

    def __init__(self, container_id: str, adb_port: int) -> None:
        """
        初始化 ScrcpyTrack。

        Args:
            container_id: Docker 容器 ID 或名称
            adb_port: 宿主机上映射的 ADB 端口（暂未直接使用，保持接口兼容）
        """
        super().__init__()

        self.container_id = container_id
        self.adb_port = adb_port

        # ADB 设备标识符
        self._target_device: str = f"{REDROID_HOST}:{adb_port}"

        # 阶段 2：Scrcpy Java 服务端进程
        self._server_process: Optional[asyncio.subprocess.Process] = None

        # 阶段 3：异步 Socket 读写流
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

        # 视频分辨率（从 Scrcpy 握手头获取）
        self._video_width: int = SCRCPY_MAX_SIZE
        self._video_height: int = int(SCRCPY_MAX_SIZE * 16 / 9)  # 默认 16:9

        # 阶段 4：PyAV 底层 H.264 解码器
        self._codec: Optional[av.CodecContext] = None

        # 帧缓冲队列（解码一次可能得到多帧）
        self._frame_queue: Deque[VideoFrame] = deque()

        # 状态标志
        self._started: bool = False
        self._stopping: bool = False

        # 统计信息
        self._frame_count: int = 0
        self._last_fps_time: float = 0.0
        self._last_fps_count: int = 0

    # ========================================================================
    # 公共接口
    # ========================================================================

    async def _start_scrcpy_async(self) -> None:
        """
        异步完整初始化：推送服务端 → 建立隧道 → 拉起服务 → Socket 握手 → 初始化解码器。

        由 WebRTCManager 在创建轨道后调用。

        Raises:
            RuntimeError: 任意阶段初始化失败
        """
        try:
            logger.info(f"[ScrcpyTrack] ========== 开始初始化 (容器: {self.container_id}) ==========")

            await self._phase1_push_and_tunnel()
            await self._phase2_start_server()
            await self._phase3_socket_handshake()
            self._phase4_init_decoder()

            self._started = True
            logger.info("[ScrcpyTrack] ========== 初始化完成，开始推流 ==========")

        except Exception as e:
            logger.error(f"[ScrcpyTrack] 初始化失败: {e}", exc_info=True)
            await self._cleanup()
            raise RuntimeError(f"ScrcpyTrack 初始化失败: {e}") from e

    async def recv(self) -> VideoFrame:
        """
        获取下一帧视频（aiortc 循环调用此方法）。

        从帧缓冲队列中弹出帧；若队列为空则从 Socket 读取并解码新数据。

        Returns:
            VideoFrame: 下一帧视频（yuv420p 格式）

        Raises:
            StopAsyncIteration: 流已结束或正在停止
            RuntimeError: 解码或读取失败
        """
        if not self._started or self._stopping:
            raise StopAsyncIteration()

        while True:
            # 1. 先尝试从队列弹出已解码的帧
            if self._frame_queue:
                return self._frame_queue.popleft()

            # 2. 队列为空，从 Socket 读取下一个数据包
            try:
                await self._read_and_decode_one_packet()
            except (asyncio.IncompleteReadError, ConnectionResetError, EOFError) as e:
                logger.warning(f"[ScrcpyTrack] Socket 连接断开: {e}")
                raise StopAsyncIteration()
            except Exception as e:
                logger.error(f"[ScrcpyTrack] 读取/解码失败: {e}", exc_info=True)
                raise RuntimeError(f"视频帧读取失败: {e}") from e

    async def stop(self) -> None:
        """
        停止视频流并清理所有资源（Socket、服务端进程、ADB 隧道）。
        """
        logger.info("[ScrcpyTrack] 正在停止...")
        self._stopping = True
        self._started = False
        await self._cleanup()
        await super().stop()
        logger.info("[ScrcpyTrack] 已完全停止")

    # ========================================================================
    # 阶段 1：推送服务端 + 建立 ADB TCP 隧道
    # ========================================================================

    async def _phase1_push_and_tunnel(self) -> None:
        """
        推送 scrcpy-server.jar 到设备，并建立 ADB forward 隧道。

        Raises:
            RuntimeError: push 或 forward 命令执行失败
        """
        # --- 1.1 推送服务端 JAR ---
        logger.info(f"[ScrcpyTrack] [Phase 1] 推送 scrcpy-server.jar → /data/local/tmp/scrcpy-server.jar")
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
            raise RuntimeError(f"adb push 失败 (code {push_proc.returncode}): {err}")
        logger.info(f"[ScrcpyTrack] [Phase 1] 推送成功: {stdout.decode(errors='replace').strip()}")

        # --- 1.2 建立 ADB TCP 隧道 ---
        # 先清理可能残留的旧 forward，防止 "already forwarded" 错误
        await asyncio.create_subprocess_exec(
            "adb", "-s", self._target_device,
            "forward", "--remove", f"tcp:{SCRCPY_FORWARD_PORT}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        logger.info(f"[ScrcpyTrack] [Phase 1] 建立隧道: tcp:{SCRCPY_FORWARD_PORT} → localabstract:scrcpy")
        fwd_proc = await asyncio.create_subprocess_exec(
            "adb", "-s", self._target_device,
            "forward",
            f"tcp:{SCRCPY_FORWARD_PORT}",
            "localabstract:scrcpy",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await fwd_proc.communicate()
        if fwd_proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"adb forward 失败 (code {fwd_proc.returncode}): {err}")
        logger.info(f"[ScrcpyTrack] [Phase 1] 隧道建立成功: {stdout.decode(errors='replace').strip()}")

    # ========================================================================
    # 阶段 2：拉起 Scrcpy Java 服务端
    # ========================================================================

    async def _phase2_start_server(self) -> None:
        """
        通过 adb shell + app_process 拉起设备内的 Scrcpy Java 服务端。

        使用 control=false 确保服务端只建立单 Socket（视频通道），
        避免因缺少控制 Socket 而导致服务端无限期挂起（死锁）。

        Raises:
            RuntimeError: 服务端进程启动失败
        """
        logger.info("[ScrcpyTrack] [Phase 2] 拉起 Scrcpy Java 服务端...")

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
            "control=false",       # 单 Socket 模式，不开启控制通道
            "cleanup=false",
            f"video_bit_rate={SCRCPY_VIDEO_BITRATE}",
            f"max_size={SCRCPY_MAX_SIZE}",
            f"max_fps={SCRCPY_MAX_FPS}",
        ]

        self._server_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 给服务端一点时间完成初始化和 Socket 监听
        await asyncio.sleep(1.0)

        # 检查进程是否意外退出
        if self._server_process.returncode is not None:
            try:
                stdout, stderr = await asyncio.wait_for(
                    self._server_process.communicate(), timeout=3.0
                )
                err = stderr.decode(errors="replace").strip()
                out = stdout.decode(errors="replace").strip()
            except asyncio.TimeoutError:
                err, out = "(读取超时)", ""
            raise RuntimeError(
                f"Scrcpy 服务端意外退出 (code {self._server_process.returncode})\n"
                f"stderr: {err}\nstdout: {out}"
            )

        logger.info(f"[ScrcpyTrack] [Phase 2] 服务端已启动 (PID: {self._server_process.pid})")

    # ========================================================================
    # 阶段 3：异步 TCP Socket 握手（v3.x 13 字节握手头）
    # ========================================================================

    async def _phase3_socket_handshake(self) -> None:
        """
        连接到 ADB forward 端口，读取 Scrcpy v3.x 握手头。

        Scrcpy v3.3.x 握手协议格式（共 77 字节）：
          - 1 byte:   Dummy byte (0x00)
          - 64 bytes: Device name（UTF-8，末尾 null 填充）
          - 4 bytes:  Codec ID（ASCII 字符串，如 'h264'）
          - 4 bytes:  Width（Big-endian uint32）
          - 4 bytes:  Height（Big-endian uint32）

        带重试机制（最多 10 次，每次间隔 0.5s），等待服务端就绪。

        Raises:
            RuntimeError: 无法连接或握手失败
        """
        max_retries = 10
        retry_delay = 0.5

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"[ScrcpyTrack] [Phase 3] 尝试连接 127.0.0.1:{SCRCPY_FORWARD_PORT} "
                    f"({attempt}/{max_retries})..."
                )
                self._reader, self._writer = await asyncio.open_connection(
                    "127.0.0.1", SCRCPY_FORWARD_PORT
                )
                logger.info("[ScrcpyTrack] [Phase 3] Socket 连接成功！")
                break
            except (ConnectionRefusedError, OSError) as e:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"无法连接到 Scrcpy 服务端 "
                        f"(127.0.0.1:{SCRCPY_FORWARD_PORT})，已重试 {max_retries} 次: {e}"
                    )
                logger.debug(f"[ScrcpyTrack] [Phase 3] 连接失败，{retry_delay}s 后重试: {e}")
                await asyncio.sleep(retry_delay)

        # 读取 77 字节握手头
        # 格式：1 dummy + 64 device_name + 4 codec_id + 4 width (uint32 BE) + 4 height (uint32 BE)
        logger.info("[ScrcpyTrack] [Phase 3] 读取握手头（77 字节）...")
        handshake = await self._reader.readexactly(77)

        dummy       = handshake[0]
        device_name = handshake[1:65].rstrip(b"\x00").decode("utf-8", errors="replace")
        codec_id    = handshake[65:69].decode("ascii", errors="replace").strip("\x00")
        width       = struct.unpack(">I", handshake[69:73])[0]   # uint32 BE
        height      = struct.unpack(">I", handshake[73:77])[0]   # uint32 BE

        # 保存视频分辨率供触摸坐标转换使用
        self._video_width = width
        self._video_height = height

        logger.info(
            f"[ScrcpyTrack] [Phase 3] 握手完成: "
            f"dummy=0x{dummy:02X}, device='{device_name}', codec='{codec_id}', 分辨率={width}x{height}"
        )

    # ========================================================================
    # 获取视频分辨率（供前端坐标转换使用）
    # ========================================================================

    def get_video_resolution(self) -> tuple[int, int]:
        """
        获取 Scrcpy 实际视频分辨率。

        Returns:
            tuple[int, int]: (宽度, 高度)
        """
        return (self._video_width, self._video_height)

    # ========================================================================
    # 阶段 4：初始化 PyAV 底层 H.264 解码器
    # ========================================================================

    def _phase4_init_decoder(self) -> None:
        """
        使用 PyAV 底层 API 初始化 H.264 解码器。

        坚决不使用 av.open(pipe)，避免阻塞 + 死锁问题。
        """
        logger.info("[ScrcpyTrack] [Phase 4] 初始化 PyAV 底层 H.264 解码器...")
        self._codec = av.CodecContext.create("h264", "r")
        logger.info(f"[ScrcpyTrack] [Phase 4] 解码器就绪: {self._codec.name}")

    # ========================================================================
    # recv() 核心逻辑：读取单个 Scrcpy 数据包并解码
    # ========================================================================

    async def _read_and_decode_one_packet(self) -> None:
        """
        从 Socket 读取一个 Scrcpy v3.x 格式的视频数据包并解码。

        Scrcpy v3.x 视频帧格式：
          - 8 bytes: PTS（Big-endian uint64）
              * 最高位为 1 (>= 2^63)：配置包（SPS/PPS），解码但不入队
              * 最高位为 0：普通视频帧
          - 4 bytes: 数据长度 Size（Big-endian uint32）
          - N bytes: H.264 裸流数据（NALU 格式）

        解码后的 VideoFrame 转换为 yuv420p 并存入 self._frame_queue。
        """
        assert self._reader is not None and self._codec is not None

        # 读取 12 字节帧头
        header = await self._reader.readexactly(12)
        pts_raw = struct.unpack(">Q", header[:8])[0]   # uint64 BE
        size    = struct.unpack(">I", header[8:12])[0]  # uint32 BE

        is_config = bool(pts_raw & SCRCPY_PTS_CONFIG_FLAG)
        pts = pts_raw & ~SCRCPY_PTS_CONFIG_FLAG  # 去掉高位标志位，得到真实 PTS（微秒）

        # 读取 H.264 裸流数据
        data = await self._reader.readexactly(size)

        if is_config:
            logger.debug(f"[ScrcpyTrack] 收到配置包 (SPS/PPS)，size={size}，喂入解码器")

        # 送入 PyAV 解析器
        packets = self._codec.parse(data)

        for pkt in packets:
            try:
                frames = self._codec.decode(pkt)
            except Exception as e:
                logger.warning(f"[ScrcpyTrack] 解码失败（跳过此包）: {e}")
                continue

            for frame in frames:
                if is_config:
                    # 配置包解出的帧不入队（通常也不会有有效图像帧）
                    continue

                # 转换为 yuv420p 供 aiortc 编码
                try:
                    video_frame = self._convert_frame(frame, pts)
                    self._frame_queue.append(video_frame)
                    self._update_fps_stats()
                except Exception as e:
                    logger.warning(f"[ScrcpyTrack] 帧转换失败（跳过）: {e}")

    def _convert_frame(self, frame: av.VideoFrame, pts_us: int) -> VideoFrame:
        """
        将 PyAV 解码帧转换为 aiortc 可用的 VideoFrame。

        Args:
            frame: PyAV 解码的原始帧
            pts_us: 从 Scrcpy 帧头读取的 PTS（微秒）

        Returns:
            VideoFrame: yuv420p 格式，设置了正确的 pts 和 time_base
        """
        # 确保是 yuv420p 格式
        pix_fmt = frame.format.name if hasattr(frame.format, "name") else str(frame.pix_fmt)
        if pix_fmt in ("yuv420p", "yuvj420p"):
            ndarray = frame.to_ndarray(format="yuv420p")
        else:
            ndarray = frame.to_ndarray(format="yuv420p")

        video_frame = VideoFrame.from_ndarray(ndarray, format="yuv420p")

        # PTS 转换：Scrcpy 提供的 PTS 单位为微秒，time_base = 1/1_000_000
        # aiortc 偏好 time_base = 1/90000，转换一下
        if pts_us > 0:
            video_frame.pts = pts_us * 90 // 1000  # 微秒 → 90kHz ticks（近似）
        else:
            video_frame.pts = self._frame_count

        video_frame.time_base = Fraction(1, 90000)

        return video_frame

    def _update_fps_stats(self) -> None:
        """
        更新帧计数并定期打印 FPS 统计。
        """
        self._frame_count += 1

        if self._frame_count == 1:
            logger.info(
                f"[ScrcpyTrack] ✅ 第一帧解码成功！队列长度: {len(self._frame_queue)}"
            )
            self._last_fps_time = time.time()
            self._last_fps_count = 1

        if self._frame_count % 30 == 0:
            now = time.time()
            elapsed = now - self._last_fps_time
            if elapsed > 0:
                fps = (self._frame_count - self._last_fps_count) / elapsed
                logger.info(f"[ScrcpyTrack] 帧 #{self._frame_count}，实时 FPS: {fps:.1f}")
            self._last_fps_time = now
            self._last_fps_count = self._frame_count

    # ========================================================================
    # 清理资源
    # ========================================================================

    async def _cleanup(self) -> None:
        """
        清理所有资源：Socket、服务端进程、ADB forward 隧道。

        按顺序执行，确保每一步的错误不影响后续清理。
        """
        # 1. 关闭 Socket
        if self._writer is not None:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
                logger.info("[ScrcpyTrack] Socket 已关闭")
            except Exception as e:
                logger.debug(f"[ScrcpyTrack] 关闭 Socket 时出错（忽略）: {e}")
            finally:
                self._writer = None
                self._reader = None

        # 2. 终止 Scrcpy Java 服务端进程
        if self._server_process is not None:
            try:
                if self._server_process.returncode is None:
                    self._server_process.kill()
                    await asyncio.wait_for(self._server_process.wait(), timeout=5.0)
                    logger.info("[ScrcpyTrack] Scrcpy 服务端进程已终止")
            except Exception as e:
                logger.debug(f"[ScrcpyTrack] 终止服务端进程时出错（忽略）: {e}")
            finally:
                self._server_process = None

        # 3. 移除 ADB TCP 隧道（防止端口死锁）
        try:
            logger.info(f"[ScrcpyTrack] 清理 ADB forward tcp:{SCRCPY_FORWARD_PORT}...")
            rm_proc = await asyncio.create_subprocess_exec(
                "adb", "-s", self._target_device,
                "forward", "--remove", f"tcp:{SCRCPY_FORWARD_PORT}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(rm_proc.wait(), timeout=5.0)
            logger.info(f"[ScrcpyTrack] ADB forward tcp:{SCRCPY_FORWARD_PORT} 已移除")
        except Exception as e:
            logger.debug(f"[ScrcpyTrack] 移除 ADB forward 时出错（忽略）: {e}")

        # 4. 清理解码器和帧队列
        self._codec = None
        self._frame_queue.clear()

    def __del__(self) -> None:
        """
        析构时尝试同步清理（兜底保障，主要靠 stop() 的异步清理）。
        """
        try:
            if self._server_process is not None and self._server_process.returncode is None:
                self._server_process.kill()
        except Exception:
            pass
