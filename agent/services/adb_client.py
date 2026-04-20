"""
Outland Agent - ADB Client Manager

提供与 Redroid 容器的异步 ADB 连接管理。
采用 adb-shell[async] 库直接通过 TCP 协议控制安卓设备。

核心特性（简化版 - 本地部署）：
- 单例模式：全局唯一的 AdbManager 实例
- 连接缓存：复用 ADB TCP 连接，避免重复握手
- 简化的端口发现：直接使用 5555 端口
"""

import asyncio
import collections
import logging
import os
import socket
from typing import Dict, Optional

import docker
from adb_shell.adb_device_async import AdbDeviceTcpAsync

from fastapi import HTTPException

# 配置日志
logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# ADB Server 配置（从环境变量读取）
ADB_SERVER_HOST: str = os.environ.get("ADB_SERVER_HOST", "127.0.0.1")
ADB_SERVER_PORT: int = int(os.environ.get("ADB_SERVER_PORT", "5037"))

# Redroid 主机地址
REDRoid_HOST: str = os.environ.get("REDROID_HOST", "127.0.0.1")

# Redroid 容器的 ADB 服务端口
REDRoid_ADB_PORT: int = int(os.environ.get("REDROID_ADB_PORT", "5555"))

# ADB 连接超时时间（秒）
ADB_CONNECT_TIMEOUT: float = 10.0

# ADB Shell 执行超时时间（秒）
ADB_SHELL_TIMEOUT: float = 5.0


# ============================================================================
# ADB 设备异常类
# ============================================================================

class AdbOperationError(Exception):
    """ADB 操作失败异常"""
    pass


class AdbConnectionError(Exception):
    """ADB 连接失败异常"""
    pass


# ============================================================================
# AdbManager 单例类
# ============================================================================

class AdbManager:
    """
    ADB 设备管理器（单例模式）
    
    负责管理与所有安卓容器的异步 ADB 连接。
    简化版：直接连接 localhost:5555
    
    Attributes:
        _instance: 单例实例
        _devices: 设备连接缓存字典，以 container_id 为键
        _locks: 每个容器的异步锁字典，防止并发握手踩踏
        _screen_sizes: 缓存每个容器的实际屏幕分辨率
    """
    
    _instance: Optional["AdbManager"] = None
    
    def __new__(cls) -> "AdbManager":
        """确保全局只有一个 AdbManager 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """
        初始化 AdbManager
        """
        if self._initialized:
            return
        
        self._devices: Dict[str, AdbDeviceTcpAsync] = {}
        self._locks: Dict[str, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self._initialized = True
        # 缓存每个容器的实际屏幕分辨率
        self._screen_sizes: Dict[str, tuple[int, int]] = {}
    
    # =========================================================================
    # 公开 API：底层动作封装
    # =========================================================================
    
    async def tap(self, container_id: str, x: int, y: int) -> None:
        """
        执行屏幕点击操作
        
        Args:
            container_id: Docker 容器 ID 或名称
            x: 点击的 X 坐标
            y: 点击的 Y 坐标
            
        Raises:
            HTTPException: 容器不存在或 ADB 连接失败
        """
        await self._execute(container_id, f"input tap {x} {y}")
    
    async def swipe(
        self,
        container_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int = 300
    ) -> None:
        """
        执行屏幕滑动操作
        
        Args:
            container_id: Docker 容器 ID 或名称
            x1: 起始 X 坐标
            y1: 起始 Y 坐标
            x2: 结束 X 坐标
            y2: 结束 Y 坐标
            duration: 滑动持续时间（毫秒），默认 300ms
            
        Raises:
            HTTPException: 容器不存在或 ADB 连接失败
        """
        await self._execute(
            container_id,
            f"input swipe {x1} {y1} {x2} {y2} {duration}"
        )
    
    async def input_text(self, container_id: str, text: str) -> None:
        """
        执行文本输入操作
        
        Args:
            container_id: Docker 容器 ID 或名称
            text: 要输入的文本内容
            
        Raises:
            HTTPException: 容器不存在或 ADB 连接失败
            
        Note:
            文本会经过严格的 Shell 转义，防止注入攻击。
            单引号会被转义为 '\''（单引号-反斜杠-单引号-单引号）
        """
        escaped = self._escape_shell_text(text)
        await self._execute(container_id, f"input text {escaped}")
    
    async def keyevent(self, container_id: str, keycode: int) -> None:
        """
        执行按键事件
        
        Args:
            container_id: Docker 容器 ID 或名称
            keycode: Android 按键码（如 26=POWER, 4=BACK, 3=HOME）
            
        Raises:
            HTTPException: 容器不存在或 ADB 连接失败
        """
        await self._execute(container_id, f"input keyevent {keycode}")
    
    # =========================================================================
    # 屏幕分辨率和坐标转换
    # =========================================================================
    
    async def get_screen_size(self, container_id: str) -> tuple[int, int]:
        """
        获取容器的实际屏幕分辨率
        
        使用 `wm size` 命令获取物理屏幕分辨率。
        结果会被缓存以提高性能。
        
        Args:
            container_id: Docker 容器 ID 或名称
            
        Returns:
            tuple[int, int]: (宽度, 高度)
        """
        # 检查缓存
        if container_id in self._screen_sizes:
            return self._screen_sizes[container_id]
        
        # 执行 wm size 命令
        result = await self._execute(container_id, "wm size")
        
        # 解析输出，如 "Physical size: 720x1280"
        import re
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", result)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
        else:
            # 默认值
            width = 720
            height = 1280
        
        # 缓存结果
        self._screen_sizes[container_id] = (width, height)
        logger.info(f"[AdbManager] 屏幕分辨率 {container_id}: {width}x{height}")
        return (width, height)
    
    async def _convert_coordinates(
        self,
        container_id: str,
        x: int,
        y: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> tuple[int, int]:
        """
        将 Scrcpy 视频流坐标转换为实际屏幕坐标
        
        由于 Scrcpy 视频流可能经过缩放，需要将触摸坐标从视频分辨率
        转换为实际屏幕分辨率。
        
        Args:
            container_id: Docker 容器 ID 或名称
            x: Scrcpy 视频中的 X 坐标
            y: Scrcpy 视频中的 Y 坐标
            scrcpy_width: Scrcpy 视频宽度
            scrcpy_height: Scrcpy 视频高度
            
        Returns:
            tuple[int, int]: (实际屏幕 X, 实际屏幕 Y)
        """
        screen_width, screen_height = await self.get_screen_size(container_id)
        
        # 计算缩放比例
        scale_x = screen_width / scrcpy_width
        scale_y = screen_height / scrcpy_height
        
        # 转换坐标
        real_x = int(x * scale_x)
        real_y = int(y * scale_y)
        
        logger.debug(
            f"[AdbManager] 坐标转换 {container_id}: "
            f"({x}, {y}) @ {scrcpy_width}x{scrcpy_height} → "
            f"({real_x}, {real_y}) @ {screen_width}x{screen_height}"
        )
        
        return (real_x, real_y)
    
    async def tap_with_conversion(
        self,
        container_id: str,
        x: int,
        y: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> None:
        """
        执行屏幕点击操作（带坐标转换）
        
        将 Scrcpy 视频流坐标转换为实际屏幕坐标后执行点击。
        
        Args:
            container_id: Docker 容器 ID 或名称
            x: Scrcpy 视频中的 X 坐标
            y: Scrcpy 视频中的 Y 坐标
            scrcpy_width: Scrcpy 视频宽度
            scrcpy_height: Scrcpy 视频高度
            
        Raises:
            HTTPException: 容器不存在或 ADB 连接失败
        """
        real_x, real_y = await self._convert_coordinates(
            container_id, x, y, scrcpy_width, scrcpy_height
        )
        await self._execute(container_id, f"input tap {real_x} {real_y}")
    
    async def swipe_with_conversion(
        self,
        container_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int,
        scrcpy_width: int,
        scrcpy_height: int
    ) -> None:
        """
        执行屏幕滑动操作（带坐标转换）
        
        将 Scrcpy 视频流坐标转换为实际屏幕坐标后执行滑动。
        
        Args:
            container_id: Docker 容器 ID 或名称
            x1: 起始 X 坐标（Scrcpy 视频坐标）
            y1: 起始 Y 坐标（Scrcpy 视频坐标）
            x2: 结束 X 坐标（Scrcpy 视频坐标）
            y2: 结束 Y 坐标（Scrcpy 视频坐标）
            duration: 滑动持续时间（毫秒）
            scrcpy_width: Scrcpy 视频宽度
            scrcpy_height: Scrcpy 视频高度
            
        Raises:
            HTTPException: 容器不存在或 ADB 连接失败
        """
        real_x1, real_y1 = await self._convert_coordinates(
            container_id, x1, y1, scrcpy_width, scrcpy_height
        )
        real_x2, real_y2 = await self._convert_coordinates(
            container_id, x2, y2, scrcpy_width, scrcpy_height
        )
        await self._execute(
            container_id,
            f"input swipe {real_x1} {real_y1} {real_x2} {real_y2} {duration}"
        )
    
    # =========================================================================
    # 连接管理
    # =========================================================================
    
    async def _get_or_connect(self, container_id: str) -> AdbDeviceTcpAsync:
        """
        获取或创建 ADB 设备连接
        
        Args:
            container_id: Docker 容器 ID 或名称
            
        Returns:
            AdbDeviceTcpAsync: ADB 设备对象
            
        Raises:
            HTTPException: 容器不存在或连接失败
        """
        # 如果已有缓存连接，直接返回
        if container_id in self._devices:
            return self._devices[container_id]
        
        # 使用容器级别的锁防止并发握手踩踏
        async with self._locks[container_id]:
            # 双重检查：获取锁后再次确认连接是否已建立
            if container_id in self._devices:
                return self._devices[container_id]
            
            # 建立新连接
            await self._connect_device(container_id)
            return self._devices[container_id]
    
    async def _connect_device(self, container_id: str) -> None:
        """
        建立与指定容器的 ADB TCP 连接
        
        Args:
            container_id: Docker 容器 ID 或名称
            
        Raises:
            HTTPException: 容器不存在或连接失败
        """
        try:
            # 获取宿主机上映射的外部端口
            host_port = self._get_container_adb_port(container_id)
            
            # 直接连接 localhost（Agent 与 Redroid 同机部署）
            device = AdbDeviceTcpAsync(REDRoid_HOST, host_port)
            
            # 连接设备（跳过 RSA 认证）
            # 新版本 adb-shell 的 connect() 不接受参数
            await device.connect()
            
            # 缓存连接
            self._devices[container_id] = device
            
        except docker.errors.NotFound:
            raise HTTPException(
                status_code=404,
                detail=f"容器 {container_id} 不存在"
            )
        except socket.timeout:
            raise HTTPException(
                status_code=504,
                detail=f"ADB 连接超时：容器 {container_id} 的 {REDRoid_ADB_PORT}/tcp 端口无响应"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"ADB 连接失败: {str(e)}"
            )
    
    def _get_container_adb_port(self, container_id: str) -> int:
        """
        获取容器内部 5555/tcp 端口在宿主机上映射的实际端口
        
        由于 Agent 使用 host 网络模式，直接返回 5555。
        只有在需要端口映射时才查询 Docker API。
        
        Args:
            container_id: Docker 容器 ID 或名称
            
        Returns:
            int: 宿主机上映射的端口（host 模式下为 5555）
        """
        try:
            # 首先检查 Docker socket 是否存在
            docker_socket = "/var/run/docker.sock"
            if not os.path.exists(docker_socket):
                # Docker socket 不存在（host 网络模式），直接返回默认端口
                logger.info(f"Docker socket 不存在，使用 host 网络模式，直接返回 {REDRoid_ADB_PORT}")
                return REDRoid_ADB_PORT
            
            client = docker.from_env()
            container = client.containers.get(container_id)
            
            ports = container.ports
            container_port_str = f"{REDRoid_ADB_PORT}/tcp"
            
            if ports and container_port_str in ports:
                host_bindings = ports[container_port_str]
                if host_bindings and len(host_bindings) > 0:
                    return int(host_bindings[0]["HostPort"])
            
            # 如果没有端口映射（host 网络模式），直接返回 5555
            return REDRoid_ADB_PORT
            
        except FileNotFoundError:
            # Docker socket 不存在，假设使用 host 网络模式
            logger.info(f"Docker socket 不存在，使用 host 网络模式，直接返回 {REDRoid_ADB_PORT}")
            return REDRoid_ADB_PORT
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"容器 {container_id} 不存在")
        except HTTPException:
            raise
        except Exception as e:
            # 如果是 Docker 连接错误，假设 host 网络模式
            if "docker" in str(e).lower() or "socket" in str(e).lower():
                logger.info(f"Docker 连接失败 ({str(e)}), 使用 host 网络模式，返回 {REDRoid_ADB_PORT}")
                return REDRoid_ADB_PORT
            raise HTTPException(status_code=500, detail=f"获取容器端口映射失败: {str(e)}")
    
    async def _execute(self, container_id: str, command: str) -> str:
        """
        在指定容器上执行 ADB Shell 命令
        
        包含僵尸连接自愈机制：第一次失败后会自动剔除死连接并重试。
        
        Args:
            container_id: Docker 容器 ID 或名称
            command: 要执行的 shell 命令
            
        Returns:
            str: 命令执行结果
            
        Raises:
            HTTPException: 容器不存在或命令执行失败
        """
        device = await self._get_or_connect(container_id)
        
        for attempt in range(2):
            try:
                # 执行 shell 命令
                result = await asyncio.wait_for(
                    device.shell(command),
                    timeout=ADB_SHELL_TIMEOUT
                )
                # 处理 bytes 和 str 两种返回类型（不同 ADB 库版本可能不同）
                if isinstance(result, bytes):
                    return result.decode("utf-8", errors="replace")
                elif isinstance(result, str):
                    return result
                else:
                    return str(result) if result else ""
                
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=504,
                    detail=f"ADB Shell 执行超时：{command}"
                )
            except (socket.error, ConnectionResetError, ConnectionRefusedError) as e:
                # 捕获连接异常，进行自愈
                self._devices.pop(container_id, None)
                
                if attempt == 0:
                    # 第一次失败：剔除死连接并尝试重建
                    continue
                else:
                    # 第二次仍然失败
                    raise HTTPException(
                        status_code=500,
                        detail=f"ADB 连接已断开且无法重建: {str(e)}"
                    )
            except Exception as e:
                # 其他异常直接上报
                raise HTTPException(
                    status_code=500,
                    detail=f"ADB Shell 执行失败: {str(e)}"
                )
        
        raise HTTPException(
            status_code=500,
            detail="ADB 执行异常：未知错误"
        )
    
    # =========================================================================
    # 工具方法
    # =========================================================================
    
    @staticmethod
    def _escape_shell_text(text: str) -> str:
        """
        将文本转义为安全的 Shell 字符串
        
        采用单引号包裹 + 内部单引号转义的方式。
        例如：I'm Bot -> 'I'\\''m Bot'
        
        Args:
            text: 原始文本
            
        Returns:
            str: 转义后的安全字符串
        """
        # 将内部单引号转义为 '\'' (单引号-反斜杠-单引号-单引号)
        escaped = text.replace("'", "'\\''")
        return f"'{escaped}'"
    
    async def close(self, container_id: str) -> None:
        """
        关闭指定容器的 ADB 连接
        
        Args:
            container_id: Docker 容器 ID 或名称
        """
        if container_id in self._devices:
            try:
                await self._devices[container_id].close()
            except Exception:
                pass
            finally:
                self._devices.pop(container_id, None)
    
    async def close_all(self) -> None:
        """关闭所有 ADB 连接"""
        for container_id in list(self._devices.keys()):
            await self.close(container_id)


# ============================================================================
# 全局实例获取函数
# ============================================================================

def get_adb_manager() -> AdbManager:
    """
    获取 AdbManager 全局单例实例
    
    Returns:
        AdbManager: ADB 管理器实例
    """
    return AdbManager()
