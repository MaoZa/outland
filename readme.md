# Outland 系统架构文档

> 本文档详细描述 Outland 安卓云容器平台的技术架构、模块设计、数据流和部署方案。

---

## 1. 项目概述

### 1.1 项目定位

**Outland** 是一个开源的安卓云容器平台，允许用户在 Linux 服务器上自托管 Android 11 实例。核心功能包括云游戏串流和脚本自动化控制。

### 1.2 核心功能

| 功能 | 描述 |
|------|------|
| Docker 容器化 Android | 基于 Redroid 在 Docker 中运行完整的 Android 11 |
| 云游戏串流 | 通过 WebRTC 实现低延迟实时屏幕串流 |
| 远程控制 | ADB 异步控制，支持点击、滑动、文本输入等操作 |
| 脚本自动化 | 提供 RESTful API 接口，便于集成自动化脚本 |
| 内网穿透友好 | 支持 STUN 服务器穿透 NAT，支持远程 Agent 代理部署 |

### 1.3 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| **底层** | Redroid (Android 11 in Docker) | 容器化安卓环境 |
| **后端** | Python + FastAPI | API 网关，容器生命周期管理 |
| **容器控制** | Docker SDK for Python | 管理 Redroid 容器的创建/启停 |
| **自动化与控制** | ADB (adb-shell[async]) | 点击、滑动、输入等操作 |
| **流媒体** | Scrcpy 协议 + aiortc + WebRTC | 视频捕获和实时串流 |
| **前端** | Next.js + TailwindCSS | Web UI |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           用户浏览器 / 客户端                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼ HTTPS/HTTP
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (Next.js)                             │
│                           localhost:3000 / nginx:80                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Dashboard (首页)     │  WebRTC Player (播放器)  │  APK Uploader   │    │
│  │  - 实例列表           │  - 视频流播放           │  - 文件上传     │    │
│  │  - 创建/删除容器      │  - 触摸控制           │  - 安装进度     │    │
│  │  - Agent 选择         │  - 文本输入           │                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ /api/*
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Backend (FastAPI)                                 │
│                           localhost:8000                                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│  │  /api/health │ │  /api/inst- │ │  /api/stream │ │  /api/agents │       │
│  │   健康检查    │ │   ances     │ │   /webrtc    │ │   /register  │       │
│  │             │ │   实例管理   │ │   流媒体路由  │ │   心跳保活   │       │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘       │
│                                    │                                        │
│                    ┌───────────────┼───────────────┐                       │
│                    │               │               │                        │
│                    ▼               ▼               ▼                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     Agent Registry (内存)                              │  │
│  │  { agent_id: { url, last_heartbeat, ... } }                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP/WebSocket (转发)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Remote Agent (独立宿主机)                                  │
│                         Agent:9090                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  部署在 Redroid 所在物理机上，Backend 无法直接访问 Redroid 网络          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────────────┐
│  Docker Manager     │  │  ADB Client        │  │  WebRTC Manager            │
│  - spawn_redroid() │  │  - tap()           │  │  - handle_offer()         │
│  - delete_cont-    │  │  - swipe()          │  │  - ScrcpyTrack            │
│    ainer()         │  │  - input_text()     │  │  - MediaRelay             │
│  - 端口分配(5555+)  │  │  - keyevent()      │  │  - DataChannel 控制       │
└─────────────────────┘  └─────────────────────┘  └─────────────────────────────┘
          │                           │                           │
          └───────────────────────────┼───────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Redroid Container                                   │
│                       bridge 网络 + 端口映射                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│  │  ADB Server  │ │  Android 11  │ │  Scrcpy      │ │  应用数据    │       │
│  │  :5555       │ │  System      │ │  Server      │ │  /data/data  │       │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 三层分离架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      第一层: Frontend                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Next.js + TailwindCSS + Lucide Icons                    │   │
│  │                                                         │   │
│  │ 职责：                                                  │   │
│  │ - 用户交互界面                                          │   │
│  │ - WebRTC 视频播放                                      │   │
│  │ - 控制指令发送（通过 DataChannel）                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Next.js Rewrites (相对路径 /api/*)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      第二层: Backend (API Gateway)                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ FastAPI + Pydantic + Docker SDK                        │   │
│  │                                                         │   │
│  │ 职责：                                                  │   │
│  │ - 请求转发（Frontend → Agent）                         │   │
│  │ - Agent Registry（注册/心跳/下线）                     │   │
│  │ - 实例聚合（从所有 Agent 获取容器列表）                 │   │
│  │ - CORS 配置                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      第三层: Agent (边缘节点)                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ FastAPI + aiortc + adb-shell + Docker SDK              │   │
│  │                                                         │   │
│  │ 职责：                                                  │   │
│  │ - Redroid 容器管理（创建/删除/监控）                    │   │
│  │ - ADB 控制（点击/滑动/输入/按键）                       │   │
│  │ - Scrcpy 视频捕获                                      │   │
│  │ - WebRTC 视频流推送                                    │   │
│  │ - DataChannel 控制指令接收                             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ ADB Protocol
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      第四层: Redroid (Android 容器)               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ redroid/redroid:11.0.0-latest + privileged            │   │
│  │                                                         │   │
│  │ 包含：                                                  │   │
│  │ - Android 11 System                                    │   │
│  │ - ADB Daemon (:5555)                                   │   │
│  │ - Scrcpy Server                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 模块详解

### 3.1 Frontend 模块

**技术栈**: Next.js 14 + React + TailwindCSS + TypeScript

#### 目录结构

```
frontend/
├── app/
│   ├── page.tsx              # Dashboard 首页（实例列表）
│   ├── layout.tsx           # 根布局
│   └── player/[id]/page.tsx # WebRTC 播放器页面
├── components/
│   ├── WebRTCPlayer.tsx     # 核心播放器组件
│   └── ApkUploader.tsx      # APK 上传组件
└── lib/
    └── api.ts               # API 封装（Fetch 包装）
```

#### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| Dashboard | `app/page.tsx` | 显示实例列表、创建/删除容器、Agent 选择 |
| WebRTCPlayer | `components/WebRTCPlayer.tsx` | WebRTC 连接、视频播放、触摸控制、坐标映射 |
| ApkUploader | `components/ApkUploader.tsx` | APK 文件拖拽上传、安装进度 |

#### API 路由重写 (next.config.js)

```javascript
// 所有 /api/* 请求转发到 Backend
{
  source: '/api/instances',
  destination: 'http://backend:8000/api/instances',
},
{
  source: '/api/stream/webrtc/offer',
  destination: 'http://backend:8000/api/stream/webrtc/offer',
},
// ... 其他路由
```

#### WebRTC 播放器核心逻辑

```typescript
// WebRTCPlayer.tsx 关键流程
1. 创建 RTCPeerConnection（配置 STUN 服务器）
2. 创建 DataChannel ('control')
3. 创建假视频轨道（触发 Safari 包含视频 m-line）
4. 创建 SDP Offer
5. 发送到后端获取 Answer
6. 设置 RemoteDescription
7. 接收视频轨道并绑定到 <video> 元素

// 触摸控制流程
PointerEvent → clientToAndroid() → DataChannel.send({ action, x, y })
```

---

### 3.2 Backend 模块

**技术栈**: Python 3.11 + FastAPI + Pydantic + Docker SDK + httpx

#### 目录结构

```
backend/
├── main.py              # FastAPI 主入口（路由聚合、Agent Registry）
├── Dockerfile           # 容器镜像定义
├── requirements.txt     # Python 依赖
├── routers/
│   ├── automation.py    # ADB 控制路由（点击/滑动/输入/按键）
│   └── stream.py        # 流媒体路由（WebRTC Offer/Answer）
└── services/           # 预留业务逻辑目录
```

#### 核心功能

| 功能 | 实现 | 说明 |
|------|------|------|
| Agent Registry | 内存字典 `AGENT_REGISTRY` | 存储已注册的 Agent URL 和心跳时间 |
| 请求转发 | `httpx.AsyncClient` | 将请求透明转发到对应 Agent |
| 实例聚合 | `asyncio.gather()` | 并发从所有 Agent 获取容器列表 |
| CORS | FastAPI Middleware | 允许 Frontend 跨域访问 |

#### Agent Registry 机制

```python
# Backend 内存状态
AGENT_REGISTRY: Dict[str, dict] = {
    "agent-node-01": {
        "url": "http://192.168.1.101:9090",
        "last_heartbeat": 1234567890.123
    }
}

# 后台任务：定期清理超时 Agent
HEARTBEAT_TIMEOUT = 180  # 3 分钟
HEARTBEAT_CLEANUP_INTERVAL = 60  # 每 60 秒清理一次
```

#### 请求转发流程

```
Frontend                    Backend                     Agent
   │                          │                          │
   │ POST /api/action/click   │                          │
   │─────────────────────────>│                          │
   │                          │ POST /api/action/click   │
   │                          │─────────────────────────>│
   │                          │                          │
   │                          │    { success: true }     │
   │                          │<─────────────────────────│
   │                          │                          │
   │    { success: true }     │                          │
   │<─────────────────────────│                          │
```

---

### 3.3 Agent 模块

**技术栈**: Python 3.11 + FastAPI + aiortc + adb-shell + Docker SDK

#### 目录结构

```
agent/
├── main.py                   # FastAPI 主入口
├── Dockerfile                # Agent 容器镜像
├── requirements.txt          # Python 依赖
├── start_adb.sh             # ADB Server 启动脚本
├── docker-compose.yml       # Agent + Redroid 编排
└── services/
    ├── docker_manager.py    # 容器生命周期管理
    ├── adb_client.py        # ADB 异步控制
    ├── scrcpy_track.py      # Scrcpy 协议实现
    └── webrtc_manager.py    # WebRTC 连接管理
```

#### 服务详解

##### 3.3.1 Docker Manager (`docker_manager.py`)

**职责**: 管理 Redroid 容器的创建和删除

**关键方法**:

| 方法 | 描述 |
|------|------|
| `spawn_redroid()` | 创建 Redroid 容器，自动分配 5555-5600 空闲端口 |
| `delete_container()` | 删除指定容器（支持 force） |
| `list_containers()` | 获取 Redroid 容器列表 |

**端口分配逻辑**:

```python
class DockerManager:
    CONTAINER_PORT = 5555      # Redroid 内部 ADB 端口
    PORT_RANGE_START = 5555   # 宿主机端口范围起点
    PORT_RANGE_END = 5600     # 宿主机端口范围终点
    
    # 使用 asyncio.Lock 防止端口分配竞态
    _port_lock: asyncio.Lock()
```

**Redroid 启动参数**:

```python
android_args = (
    f"/init qemu=1 "                    # QEMU 虚拟化
    f"androidboot.redroid_width={width} "  # 屏幕宽度
    f"androidboot.redroid_height={height} " # 屏幕高度
    f"androidboot.redroid_fps={fps} "   # 帧率
    f"androidboot.redroid_device_model={device_model}" # 设备型号
)
```

**⚠️ 重要约束**: Redroid 容器必须使用 bridge 网络模式，禁止 host 模式（会导致 Exit 129）

##### 3.3.2 ADB Client (`adb_client.py`)

**职责**: 与 Redroid 容器建立 ADB 连接，执行控制命令

**关键方法**:

| 方法 | 描述 |
|------|------|
| `tap(x, y)` | 点击屏幕坐标 |
| `swipe(x1, y1, x2, y2, duration)` | 滑动操作 |
| `input_text(text)` | 文本输入 |
| `keyevent(keycode)` | 按键事件 |
| `tap_with_conversion()` | 带坐标转换的点击 |
| `get_screen_size()` | 获取实际屏幕分辨率 |

**连接发现逻辑**:

```python
def _get_redroid_host() -> str:
    # 1. 环境变量（最高优先级）
    env_host = os.environ.get("REDROID_HOST")
    if env_host:
        return env_host
    # 2. 宿主机模式：直接 localhost
    if not os.path.exists("/.dockerenv"):
        return "localhost"
    # 3. Docker 容器模式
    return "host.docker.internal"
```

**ADB 连接架构**:

```
Agent (host 网络)              Redroid (bridge + 端口映射)
┌───────────────┐              ┌───────────────────────────┐
│ ADB Client   │ ── localhost ──>│  localhost:5555          │
│ (adb-shell)  │              │  (端口映射到宿主机)       │
└───────────────┘              └───────────────────────────┘
```

**单例模式**:

```python
class AdbManager:
    _instance: Optional["AdbManager"] = None
    
    def __new__(cls) -> "AdbManager":
        # 全局只有一个实例
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

##### 3.3.3 Scrcpy Track (`scrcpy_track.py`)

**职责**: 纯 Python 实现 Scrcpy v3.x Client 协议，捕获视频流

**核心流程（四阶段）**:

```python
class ScrcpyTrack(MediaStreamTrack):
    """
    继承 aiortc MediaStreamTrack，作为视频轨道接入 WebRTC
    """
    
    async def _start_scrcpy_async(self):
        await self._phase1_push_and_tunnel()  # 推送 scrcpy-server + 建立 ADB forward
        await self._phase2_start_server()     # 拉起 Java 服务端
        await self._phase3_socket_handshake() # Socket 握手（77 字节）
        self._phase4_init_decoder()            # 初始化 PyAV H.264 解码器
```

**Scrcpy 握手协议 (v3.3.x)**:

```
共 77 字节：
┌────────┬──────────────────────┬──────────┬─────────────┬─────────────┐
│ 1 Byte │ 64 Bytes            │ 4 Bytes  │ 4 Bytes     │ 4 Bytes    │
│ Dummy  │ Device Name (UTF-8) │ Codec ID │ Width (BE)  │ Height (BE)│
└────────┴──────────────────────┴──────────┴─────────────┴─────────────┘
```

**视频帧格式 (v3.x)**:

```
┌─────────────────┬───────────────┬────────────────────┐
│ 8 Bytes (PTS)  │ 4 Bytes (Size) │ N Bytes (H.264)  │
│ - PTS 最高位=1: 配置包(SPS/PPS)│                   │
│ - PTS 最高位=0: 视频帧        │                   │
└─────────────────┴───────────────┴────────────────────┘
```

**关键技术要点**:

- `control=false`: 单 Socket 模式，避免死锁
- `av.CodecContext.create('h264', 'r')`: 底层 API 解码
- deque 帧缓冲队列: 流畅无阻塞

##### 3.3.4 WebRTC Manager (`webrtc_manager.py`)

**职责**: 管理 WebRTC 连接，处理 SDP Offer/Answer 交换

**核心方法**:

| 方法 | 描述 |
|------|------|
| `handle_offer()` | 处理 WebRTC Offer，返回 Answer |
| `get_webrtc_manager()` | 获取单例实例 |
| `close_all()` | 关闭所有连接 |

**SDP Offer 处理流程**:

```python
async def handle_offer(self, container_id, sdp, offer_type):
    # 1. 创建 RTCPeerConnection（配置 STUN 服务器）
    pc = RTCPeerConnection(configuration=RTCConfiguration(
        iceServers=[
            RTCIceServer(urls=["stun:stun.miwifi.com:3478"]),
            RTCIceServer(urls=["stun:stun.chat.bilibili.com:3478"])
        ]
    ))
    
    # 2. 创建 ScrcpyTrack 视频轨道
    track = ScrcpyTrack(container_id, adb_port)
    await track._start_scrcpy_async()
    
    # 3. 使用 MediaRelay 复用视频流
    relayed_track = self._relay.subscribe(track)
    pc.addTrack(relayed_track)
    
    # 4. 创建 DataChannel
    backend_dc = pc.createDataChannel("control", ordered=True)
    
    # 5. 设置远端描述
    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
    
    # 6. 创建 Answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    return pc.localDescription
```

**DataChannel 控制指令处理**:

```python
# 支持的指令格式
{"action": "click", "x": 100, "y": 200}
{"action": "swipe", "x1": 100, "y1": 200, "x2": 300, "y2": 400, "duration": 300}
{"action": "input", "text": "hello"}
{"action": "keyevent", "keycode": 26}
{"action": "long_press", "x": 100, "y": 200}
{"action": "config"}  # 请求分辨率配置
```

**STUN 服务器配置**:

```python
# 使用国内可用的 STUN 服务器解决 NAT 穿透
iceServers=[
    "stun:stun.miwifi.com:3478",      # 小米
    "stun:stun.chat.bilibili.com:3478" # B站
]
```

**aioice Monkey Patch**:

修复 Docker 容器中 ifaddr 获取物理网卡失败的问题：

```python
import aioice.ice
_original_get_host_addresses = aioice.ice.get_host_addresses

def patched_get_host_addresses(use_ipv4, use_ipv6):
    addresses = _original_get_host_addresses(use_ipv4, use_ipv6)
    if "0.0.0.0" not in addresses:
        addresses.append("0.0.0.0")  # fallback
    return addresses

aioice.ice.get_host_addresses = patched_get_host_addresses
```

---

## 4. 数据流

### 4.1 WebRTC 串流流程

```
用户浏览器                    Frontend                  Backend                   Agent                    Redroid
    │                           │                         │                         │                       │
    │  1. 点击"连接"            │                         │                         │                       │
    │─────────────────────────>│                         │                         │                       │
    │                          │                         │                         │                       │
    │  2. 创建 RTCPeerConnection│                         │                         │                       │
    │  3. 创建 SDP Offer       │                         │                         │                       │
    │                          │                         │                         │                       │
    │  4. POST /api/stream/webrtc/offer                  │                         │                       │
    │─────────────────────────>│                         │                         │                       │
    │                          │  5. 转发 Offer          │                         │                       │
    │                          │────────────────────────>│                         │                       │
    │                          │                         │  6. POST /api/stream/webrtc/offer                  │
    │                          │                         │────────────────────────>│                       │
    │                          │                         │                         │  7. 创建 ScrcpyTrack │
    │                          │                         │                         │───────────────────────────>│
    │                          │                         │                         │                       │ 8. 推送 scrcpy-server
    │                          │                         │                         │                       │ 9. 启动 Java 服务端
    │                          │                         │                         │                       │ 10. Socket 握手
    │                          │                         │                         │                       │<───────────────────────────>│
    │                          │                         │                         │                       │
    │                          │                         │  11. 创建 Answer        │                       │
    │                          │                         │<────────────────────────│                       │
    │                          │  12. 返回 Answer        │                         │                       │
    │                          │<────────────────────────│                         │                       │
    │  13. 返回 Answer         │                         │                         │                       │
    │<─────────────────────────│                         │                         │                       │
    │                          │                         │                         │                       │
    │  14. ICE Candidate 收集  │                         │                         │                       │
    │<────────────────────────>│                         │                         │                       │
    │                          │                         │                         │                       │
    │  15. 视频流开始推送      │                         │                         │                       │
    │<─────────────────────────────────────────────────────────────────────────────────────────────────────────│
    │                          │                         │                         │                       │
    │  16. 用户触摸屏幕        │                         │                         │                       │
    │─────────────────────────>│                         │                         │                       │
    │                          │  17. 坐标转换          │                         │                       │
    │                          │  18. DataChannel.send()│                         │                       │
    │<─────────────────────────────────────────────────────────────────────────────────────────────────────────│
    │                          │                         │                         │                       │
    │                          │                         │  19. 解析指令           │                       │
    │                          │                         │────────────────────────>│                       │
    │                          │                         │                         │  20. ADB tap()        │
    │                          │                         │                         │───────────────────────────>│
    │                          │                         │                         │                       │ 21. 执行触摸
```

### 4.2 容器创建流程

```
用户                    Frontend                   Backend                    Agent                  Docker
  │                        │                         │                         │                      │
  │ 1. 点击"创建容器"      │                         │                         │                      │
  │───────────────────────>│                         │                         │                      │
  │                        │                         │                         │                      │
  │ 2. 选择 Agent          │                         │                         │                      │
  │    选择配置(720x1280)  │                         │                         │                      │
  │                        │                         │                         │                      │
  │ 3. POST /api/containers/spawn                    │                         │                      │
  │    {agent_id, width, height, fps}                │                         │                      │
  │───────────────────────>│                         │                         │                      │
  │                        │ 4. 转发请求              │                         │                      │
  │                        │────────────────────────>│                         │                      │
  │                        │                         │ 5. POST /api/containers/spawn                    │
  │                        │                         │────────────────────────>│                      │
  │                        │                         │                         │ 6. DockerManager    │
  │                        │                         │                         │   .spawn_redroid()  │
  │                        │                         │                         │─────────────────────>│
  │                        │                         │                         │                      │ 7. 分配端口 5555+
  │                        │                         │                         │                      │ 8. 创建容器
  │                        │                         │                         │                      │<─────────────────────│
  │                        │                         │                         │ 9. SpawnResult       │
  │                        │                         │                         │<────────────────────│
  │                        │                         │ 10. 返回 SpawnResponse   │
  │                        │                         │<────────────────────────│
  │                        │ 11. 返回 SpawnResponse  │
  │                        │<────────────────────────│
  │ 12. 显示创建成功        │
  │<──────────────────────│
```

### 4.3 APK 安装流程

```
用户                  Frontend                   Backend                    Agent                  Redroid
  │                      │                         │                         │                      │
  │ 1. 拖拽 APK 文件   │                         │                         │                      │
  │────────────────────>│                         │                         │                      │
  │                     │                         │                         │                      │
  │ 2. POST /api/apk/install (multipart/form-data)                     │
  │    {file, container_id}│                       │                         │                      │
  │────────────────────>│                         │                         │                      │
  │                     │ 3. 转发文件              │                         │                      │
  │                     │────────────────────────>│                         │                      │
  │                     │                         │ 4. 保存到临时文件        │                      │
  │                     │                         │                         │ 5. adb install       │
  │                     │                         │                         │─────────────────────>│
  │                     │                         │                         │                      │ 6. 安装 APK
  │                     │                         │                         │                      │<─────────────────────│
  │                     │                         │ 7. 返回结果              │                      │
  │                     │                         │<────────────────────────│                      │
  │                     │ 8. 返回结果             │                         │                      │
  │                     │<────────────────────────│                         │                      │
  │ 9. 显示安装成功      │
  │<────────────────────│
```

---

## 5. 部署架构

### 5.1 分布式部署（推荐）

适用于生产环境，Backend 和 Agent 分离部署：

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    用户网络                                          │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Frontend + Backend (内网/云服务器)                      │
│                                                                                      │
│  ┌─────────────────────┐  ┌─────────────────────┐                                   │
│  │  Frontend (Next.js) │  │  Backend (FastAPI)  │                                   │
│  │  端口: 3000         │  │  端口: 8000         │                                   │
│  └─────────────────────┘  └─────────────────────┘                                   │
│                                    │                                               │
│                                    │ Agent Registry                                │
│                                    │ (HTTP/HTTPS)                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        │ Internet
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Agent 宿主机 (内网穿透)                                  │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │ Agent (FastAPI)                                                               │   │
│  │ - network_mode: host                                                         │   │
│  │ - 端口: 9090                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │ Redroid 容器 (bridge 网络 + 端口映射)                                          │   │
│  │ - redroid-xxxxxxxx                                                           │   │
│  │ - 端口: 5555 (容器) → 动态端口 (宿主机)                                        │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  宿主机配置:                                                                          │
│  - CPU: AMD Ryzen 5 5600X (或更强)                                                  │
│  - 内存: 32GB+                                                                          │
│  - 内核模块: binder_linux, ashmem_linux                                              │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 单机部署

适用于开发/测试环境，所有组件运行在同一台服务器：

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - REDROID_HOST=192.168.1.103
      - AGENT_URL=http://192.168.1.103:9090

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"

  agent:
    build: ./agent
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - REDROID_HOST=localhost
      - BACKEND_URL=http://localhost:8000
```

### 5.3 网络拓扑

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Agent 宿主机 (192.168.1.103)                          │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Agent (host 网络模式, 端口 9090)                                    │   │
│  │    │                                                                  │   │
│  │    │ 连接到                                                                         │   │
│  │    ▼                                                                        │   │
│  │  ┌───────────────────────────────────────────────────────────────┐   │   │
│  │  │  Redroid 容器 (bridge 网络)                                   │   │   │
│  │  │  - 容器内部: 5555                                              │   │   │
│  │  │  - 宿主机映射: 5556 (示例)                                     │   │   │
│  │  │  - 连接地址: localhost:5556                                  │   │   │
│  │  └───────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  STUN 服务器 (用于 WebRTC NAT 穿透)                                 │   │
│  │  - stun.miwifi.com:3478                                            │   │
│  │  - stun.chat.bilibili.com:3478                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. API 参考

### 6.1 Frontend → Backend

| 接口 | 方法 | 描述 | 请求体 | 响应 |
|------|------|------|--------|------|
| `/api/instances` | GET | 获取所有实例列表 | - | `InstanceListResponse` |
| `/api/containers/spawn` | POST | 创建容器 | `SpawnRequest` | `SpawnResponse` |
| `/api/containers/{id}` | DELETE | 删除容器 | Query: `force` | `DeleteResponse` |
| `/api/stream/webrtc/offer` | POST | WebRTC Offer | `WebRTCOfferRequest` | `WebRTCAnswerResponse` |
| `/api/action/click` | POST | 点击 | `ClickRequest` | `ActionResponse` |
| `/api/action/swipe` | POST | 滑动 | `SwipeRequest` | `ActionResponse` |
| `/api/action/text` | POST | 文本输入 | `TextRequest` | `ActionResponse` |
| `/api/action/keyevent` | POST | 按键事件 | `KeyEventRequest` | `ActionResponse` |
| `/api/agents/register` | POST | Agent 注册 | `AgentRegisterRequest` | `AgentRegisterResponse` |
| `/api/agents/heartbeat` | POST | Agent 心跳 | `AgentHeartbeatRequest` | `AgentHeartbeatResponse` |
| `/api/agents/list` | GET | Agent 列表 | - | `AgentRegistryResponse` |
| `/api/apk/install` | POST | 安装 APK | multipart/form-data | `ApkInstallResponse` |

### 6.2 Backend → Agent

| 接口 | 方法 | 描述 |
|------|------|------|
| `/api/instances` | GET | 获取容器列表 |
| `/api/containers/spawn` | POST | 创建容器 |
| `/api/containers/{id}` | DELETE | 删除容器 |
| `/api/container/{id}/adb_port` | GET | 获取 ADB 端口 |
| `/api/stream/webrtc/offer` | POST | WebRTC Offer |
| `/api/action/click` | POST | 点击 |
| `/api/action/swipe` | POST | 滑动 |
| `/api/action/text` | POST | 文本输入 |
| `/api/action/keyevent` | POST | 按键事件 |
| `/api/apk/install` | POST | 安装 APK |

---

## 7. 环境变量

### 7.1 Backend 环境变量

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker Socket 地址 |
| `REDROID_HOST` | `192.168.1.101` | Redroid 宿主机地址 |
| `AGENT_URL` | `http://192.168.1.101:9090` | Agent 服务地址 |

### 7.2 Agent 环境变量

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `BACKEND_URL` | `http://localhost:8000` | Backend 服务地址 |
| `AGENT_ADVERTISED_URL` | 自动获取 | Agent 对外暴露的 URL |
| `REDROID_HOST` | `localhost` | Redroid 主机地址 |
| `REDROID_ADB_PORT` | `5555` | Redroid ADB 端口 |
| `ADB_SERVER_HOST` | `127.0.0.1` | ADB Server 地址 |
| `ADB_SERVER_PORT` | `5037` | ADB Server 端口 |
| `SCRCPY_SERVER_PATH` | `/usr/local/share/scrcpy/scrcpy-server` | Scrcpy Server 路径 |
| `AGENT_ID` | 主机名或随机 UUID | Agent 唯一标识 |

---

## 8. 开发指南

### 8.1 本地开发环境

```bash
# 1. 克隆项目
git clone https://github.com/your-repo/outland.git
cd outland

# 2. 启动后端
cd backend
pip install -r requirements.txt
python main.py  # http://localhost:8000

# 3. 启动 Agent（在另一终端）
cd agent
pip install -r requirements.txt
bash start_adb.sh &
python main.py  # http://localhost:9090

# 4. 启动前端（在另一终端）
cd frontend
npm install
npm run dev  # http://localhost:3000
```

### 8.2 目录结构

```
outland/
├── docker-compose.yml          # 主部署配置
├── setup-redroid.sh            # Redroid 一键部署脚本
├── ARCHITECTURE.md            # 本文档
├── readme.md                   # 项目说明
│
├── backend/                    # 后端服务
│   ├── main.py                 # FastAPI 主入口
│   ├── Dockerfile              # 后端容器镜像
│   ├── requirements.txt        # Python 依赖
│   └── routers/
│       ├── automation.py       # 自动化控制路由
│       └── stream.py          # WebRTC 流媒体路由
│
├── agent/                      # Agent 代理服务
│   ├── main.py                 # Agent 主入口
│   ├── Dockerfile              # Agent 容器镜像
│   ├── requirements.txt        # Python 依赖
│   ├── start_adb.sh          # ADB Server 启动脚本
│   ├── docker-compose.yml      # Agent + Redroid 编排
│   └── services/
│       ├── adb_client.py       # ADB 异步客户端
│       ├── docker_manager.py   # Docker 容器管理
│       ├── scrcpy_track.py     # Scrcpy 协议实现
│       └── webrtc_manager.py   # WebRTC 连接管理
│
└── frontend/                   # 前端应用
    ├── package.json            # Node.js 依赖
    ├── next.config.js          # Next.js 配置（API 路由重写）
    ├── app/
    │   ├── page.tsx            # Dashboard 首页
    │   ├── layout.tsx          # 根布局
    │   └── player/[id]/page.tsx # 播放器页面
    ├── components/
    │   ├── WebRTCPlayer.tsx    # WebRTC 播放器组件
    │   └── ApkUploader.tsx     # APK 上传组件
    └── lib/
        └── api.ts             # API 封装
```

### 8.3 运行测试

```bash
cd agent

# 安装测试依赖
pip install pytest pytest-asyncio

# 运行单元测试
pytest test_patch_integration.py -v
```

---

## 9. 技术亮点

### 9.1 Scrcpy 协议纯 Python 实现

`scrcpy_track.py` 完全使用 Python 实现 Scrcpy v3.3.4 协议，包含：
- 4 阶段连接流程：推送服务端 → 建立 ADB 隧道 → Socket 握手 → 视频流解析
- PyAV 解码 H.264 视频流
- 控制指令通过 Unix Socket 发送

### 9.2 WebRTC 视频流复用

`webrtc_manager.py` 使用 `aiortc` 实现 WebRTC：
- RTCPeerConnection 管理
- MediaRelay 复用视频流到多个消费者
- DataChannel 传输控制指令

### 9.3 ADB 异步控制

`adb_client.py` 基于 `adb-shell[async]` 实现：
- 异步 ADB 连接管理
- 坐标自动转换（客户端坐标 → Android 屏幕坐标）
- 连接缓存和自愈机制

### 9.4 NAT 穿透支持

使用国内可用的 STUN 服务器：
```
stun.miwifi.com:3478      # 小米
stun.chat.bilibili.com:3478 # B站
```

### 9.5 Safari WebRTC 兼容性

通过添加假视频轨道触发 Safari 包含视频 m-line：
```typescript
// WebRTCPlayer.tsx
const fakeStream = await navigator.mediaDevices.getUserMedia({
  video: { width: 1, height: 1 }
});
pc.addTrack(fakeStream.getVideoTracks()[0]);
```

---

## 10. 常见问题

### Q: Redroid 容器无法启动？

确保内核支持 binder 和 ashmem：
```bash
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
sudo modprobe ashmem_linux
```

### Q: WebRTC 连接失败？

1. 检查防火墙是否开放 UDP 端口
2. 确认 STUN 服务器可达
3. 查看 Agent 日志确认 Scrcpy 连接状态

### Q: 控制指令延迟高？

- 使用有线网络连接
- 降低视频码率或分辨率
- 启用硬件编解码（需要 NVIDIA GPU）

### Q: Agent 无法连接 Redroid？

检查网络模式配置：
- Agent 必须使用 `network_mode: host`
- Redroid 必须使用 bridge 网络模式
- 检查 `REDROID_HOST` 环境变量是否正确

---

## 11. 参考资料

- [Redroid 官方文档](https://github.com/remoteAndroid/redroid)
- [Scrcpy 协议文档](https://github.com/Genymobile/scrcpy)
- [aiortc 文档](https://aiortc.readthedocs.io/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Next.js 文档](https://nextjs.org/docs)
