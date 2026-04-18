"""
Outland Backend - Scrcpy Media Track

提供与 aiortc 兼容的视频轨道，将 scrcpy 的 H264 视频流封装为 MediaStreamTrack。

核心功能：
- 启动 scrcpy 子进程获取屏幕视频流
- 使用 PyAV 解析原始 H264 视频流
- 提供与 aiortc 兼容的 recv() 异步接口
- 正确的子进程生命周期管理（防止僵尸进程）

技术要点：
- 使用 asyncio.to_thread() 避免 PyAV 同步读取阻塞事件循环
- stderr 重定向到 DEVNULL 防止管道缓冲区死锁 (64KB)
- 正确的 pts 和 time_base 设置确保视频同步
"""

import asyncio
import subprocess
from typing import Optional, Generator

import av
from av import VideoFrame
from aiortc import MediaStreamTrack
from aiortc.mediastreams import VIDEO_CLOCK_RATE


class ScrcpyTrack(MediaStreamTrack):
    """
    Scrcpy 视频轨道类
    
    将 scrcpy 的 H264 视频流转换为 aiortc 可消费的 VideoFrame。
    
    Attributes:
        container_id: Docker 容器 ID
        adb_port: 宿主机上映射的 ADB 端口
        kind: 媒体类型，始终为 "video"
    """
    
    kind = "video"
    
    def __init__(self, container_id: str, adb_port: int) -> None:
        """
        初始化 ScrcpyTrack
        
        Args:
            container_id: Docker 容器 ID 或名称
            adb_port: 宿主机上映射的 ADB 端口
        """
        super().__init__()
        
        self.container_id = container_id
        self.adb_port = adb_port
        
        self._process: Optional[asyncio.subprocess.Process] = None
        self._container: Optional[av.container.InputContainer] = None
        self._video_stream: Optional[av.stream.Stream] = None
        self._frame_generator: Optional[Generator] = None
        self._started = False
        self._init_task: Optional[asyncio.Task] = None
        self._xvfb_proc: Optional[subprocess.Popen] = None
    
    def _start_scrcpy_sync(self) -> None:
        """
        同步启动 scrcpy 子进程并初始化 PyAV 容器
        
        Raises:
            RuntimeError: scrcpy 启动失败或 PyAV 初始化失败
        """
        import time
        import select as selector
        
        try:
            # 从环境变量获取 Redroid 主机地址（支持远程部署）
            import os
            redroid_host = os.environ.get("REDROID_HOST", "127.0.0.1")
            target_device = f"{redroid_host}:5555"

            # 先断开并重置 ADB 连接
            print(f"[ScrcpyTrack] 重置 ADB 连接...")
            subprocess.run(
                ["adb", "disconnect", target_device],
                capture_output=True,
                timeout=5
            )
            print(f"[ScrcpyTrack] 尝试连接 ADB...")
            connect_result = subprocess.run(
                ["adb", "connect", target_device],
                capture_output=True,
                text=True,
                timeout=5
            )
            print(f"[ScrcpyTrack] adb connect 结果: {connect_result.stdout.strip()}")
            
            # 使用 scrcpy v3.3.4 无头录制模式
            # --no-playback: 不在本地播放视频/音频
            # --no-window: 不打开 SDL 窗口（无需显示服务器）
            # --no-audio: 不转发音频
            # --video-codec=h264: 使用 H264 编码
            # --record: 录制到命名管道（FIFO）传输给 PyAV
            import os
            pipe_path = f"/tmp/scrcpy_{self.container_id}.pipe"
            try:
                os.unlink(pipe_path)
            except FileNotFoundError:
                pass
            os.mkfifo(pipe_path)
            
            print(f"[ScrcpyTrack] 启动 scrcpy v3 无头录制...")
            self._process = subprocess.Popen(
                [
                    "scrcpy",
                    "-s", target_device,
                    "--no-playback",
                    "--no-window",
                    "--no-audio",
                    "--video-codec=h264",
                    "--max-size=720",
                    "--max-fps=30",
                    f"--record={pipe_path}",
                    "--record-format=mkv",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._pipe_path = pipe_path
            
            # 等待 scrcpy 初始化并开始写入管道
            print(f"[ScrcpyTrack] 等待视频流开始...")
            
            # 检查进程是否正常启动（短暂等待）
            time.sleep(1)
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode('utf-8', errors='replace') if self._process.stderr else ''
                raise RuntimeError(f"scrcpy 启动失败，退出码: {self._process.returncode}, stderr: {stderr}")
            
            # 使用 PyAV 打开命名管道读取 Matroska 封装的 H264 流
            self._container = av.open(
                pipe_path,
                format='matroska',
                mode='r',
                timeout=10000000  # 10秒超时
            )
            
            # 获取视频流
            self._video_stream = self._container.streams.video[0]
            
            # 创建帧生成器
            self._frame_generator = self._container.decode(self._video_stream)
            
            self._started = True
            print(f"[ScrcpyTrack] scrcpy 启动成功")
            
        except Exception as e:
            self._cleanup()
            raise RuntimeError(f"启动 scrcpy 失败: {str(e)}")
    
    async def _start_scrcpy_async(self) -> None:
        """
        异步启动 scrcpy 子进程（使用线程池避免 Windows 兼容性问题）
        
        Raises:
            RuntimeError: scrcpy 启动失败或 PyAV 初始化失败
        """
        try:
            # 使用 asyncio.to_thread 在线程池中运行同步的 subprocess
            # 这样可以避免 Windows 上 ProactorEventLoop 的限制
            await asyncio.to_thread(self._start_scrcpy_sync)
        except Exception as e:
            raise RuntimeError(f"启动 scrcpy 失败: {str(e)}")
    
    async def recv(self) -> VideoFrame:
        """
        接收下一帧视频
        
        aiortc 会调用此方法获取视频帧。必须使用 asyncio.to_thread()
        将同步阻塞的帧读取操作放到线程池，避免阻塞事件循环。
        
        Returns:
            VideoFrame: 下一帧视频
            
        Raises:
            StopAsyncIteration: 流已结束
            RuntimeError: 流读取失败
        """
        if not self._started or self._frame_generator is None:
            raise StopAsyncIteration()
        
        try:
            # 关键：使用 asyncio.to_thread() 将同步阻塞的 PyAV 读取操作
            # 放到线程池执行，避免卡死 FastAPI 事件循环
            frame = await asyncio.to_thread(next, self._frame_generator)
            
            # 创建 aiortc 兼容的 VideoFrame
            video_frame = VideoFrame.from_ndarray(frame.to_ndarray(), format="rgb24")
            
            # 设置正确的时间戳
            # pts: presentation time stamp (显示时间戳)
            # time_base: 时间基，决定 pts 的单位
            video_frame.pts = frame.pts
            video_frame.time_base = self._video_stream.time_base if self._video_stream else (1, 30)
            
            return video_frame
            
        except StopIteration:
            # 流已结束
            raise StopAsyncIteration()
        except Exception as e:
            raise RuntimeError(f"读取视频帧失败: {str(e)}")
    
    async def stop(self) -> None:
        """
        停止视频流并清理资源
        
        必须确保 scrcpy 子进程被正确杀死，防止僵尸进程。
        """
        self._started = False
        self._cleanup()
        await super().stop()
    
    def _cleanup(self) -> None:
        """
        清理资源（同步方法）
        
        用于在 __init__ 异常或 stop() 中清理资源。
        """
        # 关闭 PyAV 容器
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
        
        # 杀死 scrcpy 子进程
        if self._process is not None:
            try:
                # 检查进程是否还在运行
                if self._process.returncode is None:
                    self._process.kill()
                # 等待进程退出并回收资源
                self._process.wait()
            except Exception:
                pass
            self._process = None
        
        self._frame_generator = None
        self._video_stream = None
        
        # 清理命名管道文件
        if hasattr(self, '_pipe_path') and self._pipe_path is not None:
            import os
            try:
                os.unlink(self._pipe_path)
            except Exception:
                pass
            self._pipe_path = None
