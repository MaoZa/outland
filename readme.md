# Outland 安卓云容器平台

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


> 面向自托管 Android 13 云游戏串流与自动化控制的开源平台。基于 Redroid 在 Docker 中运行完整 Android 系统，通过 WebRTC 实现低延迟实时视频流与远程控制。

---

## 1. 项目概述

### 1.1 核心功能

| 功能 | 描述 |
|------|------|
| Docker 容器化 Android | 基于 Redroid 13.0 在 Docker 中运行完整 Android 13 |
| 云游戏串流 | WebRTC + Scrcpy 协议，<200ms 延迟实时视频流 |
| 远程控制 | ADB 异步控制，支持点击、滑动、文本输入、按键事件 |
| 脚本自动化 | RESTful API 接口，便于集成自动化脚本 |
| 外部设备支持 | 连接真实 Android 手机，支持 MIUI 无线调试配对 |
| 多 Agent 架构 | 分布式部署，Backend 聚合多个 Agent 的容器 |
| 用户认证系统 | JWT + bcrypt 认证，用户配额管理 |
| 视频质量控制 | 高（720p/2.5Mbps）/中（480p/1.5Mbps）/低（360p/800Kbps） |
| APK/XAPK 安装 | 支持单 APK 和 XAPK（含 split APK + shared libraries） |
| 容器 Resize | 动态调整分辨率和帧率，无需重建数据 |
| Safari 兼容性 | 自动注入视频 m-line，解决 Safari WebRTC SDP 问题 |

### 1.2 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| **底层** | Redroid 13.0 (Android in Docker) | 容器化安卓环境，privileged 模式 |
| **后端** | Python 3.11 + FastAPI + Pydantic v2 | API 网关，异步架构 |
| **数据库** | SQLAlchemy + aiosqlite (SQLite) | 异步 ORM，用户/容器/配额持久化 |
| **认证** | PyJWT + bcrypt | HS256 token，24h 过期 |
| **容器控制** | Docker SDK for Python (async) | Redroid 容器生命周期管理 |
| **自动化控制** | adb-shell[async] + CLI fallback | 点击/滑动/输入，支持 TLS 外部设备 |
| **流媒体** | Scrcpy v3.3.4 + aiortc + PyAV | 视频捕获与 WebRTC 实时串流 |
| **前端** | Next.js 14 + TailwindCSS + Lucide | SSR + 响应式 UI |

### 1.3 系统拓扑

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          用户浏览器 (Browser)                                 │
│                       WebRTC 视频流 + DataChannel 控制                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTPS/HTTP
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js) :3000                              │
│  ┌─────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐ │
│  │  登录/注册       │  │  实例列表 + 外部设备    │  │  WebRTC Player        │ │
│  │  Auth Guard     │  │  创建/删除/Resize      │  │  视频播放 + 控制       │ │
│  └─────────────────┘  └────────────────────────┘  └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ /api/* (Proxy)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Backend (FastAPI) :8000                              │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Middleware: CORS / Rate Limit / Exception Handler / Request Logging   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐       │
│  │ /health │ │ /api/   │ │ /api/    │ │ /api/    │ │ /api/       │       │
│  │ 健康检查 │ │ auth    │ │ users    │ │ agents   │ │ external-   │       │
│  │         │ │ 登录注册 │ │ 用户配额 │ │ 注册心跳 │ │ devices     │       │
│  └─────────┘ └─────────┘ └──────────┘ └──────────┘ └─────────────┘       │
│                                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐     │
│  │ /api/    │ │ /api/    │ │ /api/    │ │ /api/    │ │ /api/apk     │     │
│  │ instances│ │ containers│ │ stream   │ │ action   │ │ 安装APK     │     │
│  │ 实例聚合 │ │ 容器管理 │ │ WebRTC   │ │ 控制指令 │ │             │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────┘     │
│                                    │                                        │
│                    ┌───────────────┴───────────────┐                        │
│                    ▼                               ▼                        │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │  Agent Registry (内存)       │  │  SQLite Database (异步)              │  │
│  │  { agent_id: url, heartbeat }│  │  User / Container / Quota           │  │
│  │  180s 超时清理               │  │  ExternalDevice / AgentState        │  │
│  └─────────────────────────────┘  └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP / WebSocket
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────────────┐
│   Agent A (:9090)   │  │   Agent B (:9090)   │  │   Agent C (:9090)          │
│   宿主机 192.168.1.101 │  │   宿主机 192.168.1.102 │  │   宿主机 192.168.1.103        │
│                     │  │                     │  │                             │
│  ┌────────────────┐ │  ┌────────────────┐ │  ┌────────────────────────────┐ │
│  │ Redroid 容器    │ │  │ Redroid 容器   │ │  │ 外部设备 (MIUI 无线调试)   │ │
│  │ ADB :5555→5555 │ │  │ ADB :5555→5556 │ │  │ ADB tcp:192.168.1.100:5555 │ │
│  │                 │ │  │                │ │  │ RSA 密钥认证               │ │
│  │ Scrcpy Server   │ │  │ Scrcpy Server  │ │  │ ADB Pair + Connect        │ │
│  │ H.264 视频流    │ │  │ H.264 视频流   │ │  │                            │ │
│  └────────────────┘ │  └────────────────┘ │  └────────────────────────────┘ │
└─────────────────────┘  └─────────────────────┘  └─────────────────────────────┘
```

---

## 2. 数据库模型

### 2.1 ER 关系图

```
User (1) ─────< Quota (1)
    │
    └────< Container (N)       Container ────> Agent (N:1, via agent_id)
    │
    └────< ExternalDevice (N)  ExternalDevice ───> Agent (N:1, via agent_id)

AgentState (独立记录，用于未来持久化，当前使用内存 Registry)
```

### 2.2 模型详情

| 模型 | 表名 | 关键字段 | 说明 |
|------|------|----------|------|
| **User** | `users` | id, email (unique), hashed_password, is_admin, is_active, is_verified | 用户认证 |
| **Quota** | `quotas` | user_id (FK, unique), max_containers (default=1) | 用户容器配额 |
| **Container** | `containers` | uuid, user_id (FK), agent_id, container_id, status, resolution, created_at | 容器记录 |
| **ExternalDevice** | `external_devices` | uuid, user_id (FK), agent_id, name, adb_host, adb_port, rsa_key_path, status, resolution | 外部设备 |
| **AgentState** | `agent_states` | agent_id (unique), url, last_heartbeat | Agent 持久化（备用） |

---

## 3. 模块详解

### 3.1 Frontend

**技术栈**: Next.js 14 + React 18 + TailwindCSS + Lucide Icons + TypeScript

#### 目录结构

```
frontend/
├── app/
│   ├── page.tsx                    # Dashboard：实例列表 + 创建/删除/外部设备
│   ├── layout.tsx                  # 根布局 + AuthGuard
│   ├── auth-guard.tsx              # 认证守卫：未登录重定向 /login
│   ├── login/page.tsx              # 登录/注册
│   └── player/[id]/page.tsx        # WebRTC Player：视频播放 + 控制
├── components/
│   ├── WebRTCPlayer.tsx            # 核心播放器：WebRTC + DataChannel + 坐标映射
│   └── ApkUploader.tsx            # APK/XAPK 上传安装
└── lib/
    ├── api.ts                      # 所有 API 调用（60+ 函数）
    └── auth.tsx                    # AuthContext：登录/登出/状态
```

#### 核心功能

**Dashboard (`page.tsx`)**:
- `InstanceCard` — 区分本地容器（source≠'external'）vs 外部设备（蓝色 Wifi 图标 + "远程" 标签）
- `AddExternalDeviceModal` — 3 步向导：①配对 ②连接测试 ③保存（含 MIUI 配对码）
- `CreateContainerModal` — Agent 选择 + 分辨率预设（低/高/横屏）
- `ResizeModal` — 容器分辨率调整
- `DeleteConfirmModal` — 删除确认（外部设备仅删除记录，不影响真机）

**WebRTCPlayer (`WebRTCPlayer.tsx`)**:
- 创建 RTCPeerConnection（STUN: miwifi.com, bilibili.com）
- DataChannel 'control' 发送 JSON 控制指令（click/swipe/input/keyevent/long_press）
- 坐标映射：`clientToAndroid()` 处理 4 种旋转/缩放情况
- Safari 兼容：canvas 假视频轨道确保 m-line 存在
- 质量切换：重建连接切换高/中/低三级

**API 代理 (next.config.js)**:
- 22 条 rewrite 规则，所有 `/api/*` 转发到 `backend:8000`
- `/api/external-devices/:path*`  wildcard 匹配

---

### 3.2 Backend

**技术栈**: Python 3.11 + FastAPI 0.109+ + Pydantic v2 + SQLAlchemy async + httpx

#### 目录结构

```
backend/
├── main.py                         # FastAPI 入口，10 个路由注册，lifespan 管理
├── requirements.txt                # 依赖
│
├── auth/                           # 认证模块
│   ├── jwt.py                      # create_access_token / verify_token (HS256, 24h)
│   ├── password.py                 # hash_password / verify_password (bcrypt)
│   └── dependencies.py              # get_current_user / require_admin (FastAPI Depends)
│
├── core/                           # 核心配置
│   ├── config.py                   # Pydantic Settings，OUTLAND_* 环境变量前缀
│   └── http_client.py              # httpx.AsyncClient 单例（HTTP/2，100 连接）
│
├── database/                       # 数据库层
│   ├── models.py                   # SQLAlchemy ORM：User/Container/Quota/ExternalDevice
│   └── __init__.py                 # engine / async_session_maker / get_db() / init_db()
│
├── middleware/                     # 中间件
│   ├── logging.py                  # RequestLoggingMiddleware（structlog 记录）
│   └── exception_handler.py        # ExceptionHandlerMiddleware（500 JSON）
│
├── models/                         # Pydantic Schema
│   ├── agent.py                    # AgentRegister/Heartbeat/Info/RegistryResponse
│   ├── container.py                # PortMapping/ContainerInfo/SpawnRequest/ResizeRequest
│   ├── external_device.py          # ExternalDeviceCreate/Update/Response/TestResponse
│   ├── stream.py                   # WebRTCOffer/QualityChange/ConnectionStats
│   ├── action.py                   # Click/Swipe/Text/KeyEvent/ActionResponse
│   └── apk.py                      # ApkInstallResponse
│
├── routers/                        # API 路由
│   ├── health.py                   # GET /, GET /health
│   ├── auth/__init__.py             # POST /api/auth/login, /register
│   ├── users.py                    # GET /api/users/me, PUT /api/users/admin/*
│   ├── agents.py                   # POST /api/agents/register, /heartbeat
│   ├── instances.py                # GET /api/instances（聚合所有 Agent 容器）
│   ├── containers.py               # POST /api/containers/spawn, DELETE /{id}, POST /{id}/resize
│   ├── stream.py                   # POST /api/stream/webrtc/offer, /quality, GET /stats/{id}
│   ├── actions.py                  # POST /api/action/click|swipe|text|keyevent
│   ├── apk.py                      # POST /api/apk/install
│   ├── external_devices.py         # CRUD + /pair + /test-direct
│   └── external_device_helpers.py  # is_external_device / get_external_device / resolve_agent
│
└── services/
    └── agent_registry.py           # AGENT_REGISTRY 内存字典 + cleanup_loop + fetch_agent_instances
```

#### 中间件栈（添加顺序，外层先执行）

```
1. CORSMiddleware         ← 跨域，允许 OUTLAND_CORS_ORIGINS
2. SlowAPIMiddleware      ← 全局限速
3. ExceptionHandlerMiddleware ← 未捕获异常 → 500 JSON
4. RequestLoggingMiddleware ← structlog: method, path, status, duration_ms
```

#### 环境变量（`OUTLAND_` 前缀）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_NAME` | "Outland Backend" | 应用名 |
| `DEBUG` | False | SQLAlchemy echo |
| `HOST` / `PORT` | 0.0.0.0 / 8000 | 监听地址 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/outland.db` | 数据库连接 |
| `JWT_SECRET` | "change-me-in-production" | HS256 签名密钥 |
| `JWT_ALGORITHM` | "HS256" | 算法 |
| `HEARTBEAT_TIMEOUT` | 180 | Agent 心跳超时（秒） |
| `HEARTBEAT_CLEANUP_INTERVAL` | 60 | 清理间隔（秒） |
| `HTTP_MAX_KEEPALIVE` | 20 | httpx keepalive |
| `HTTP_MAX_CONNECTIONS` | 100 | httpx 最大连接 |
| `CORS_ORIGINS` | `http://localhost:3000,...` | 允许的源 |

---

### 3.3 Agent

**技术栈**: Python 3.11 + FastAPI + aiortc + PyAV 12.3.0 + adb-shell + Docker SDK

#### 目录结构

```
agent/
├── main.py                         # FastAPI 入口，14 个端点，lifespan 心跳
├── requirements.txt                # 依赖
├── Dockerfile                      # 镜像：python:3.11 + FFmpeg + build-essential + scrcpy v3.3.4
├── docker-compose.yml               # host 网络模式 + adb-keys 持久化卷
├── start_adb.sh                    # ADB Server 启动脚本
├── .env                            # BACKEND_URL / AGENT_ADVERTISED_URL / REDROID_HOST
│
└── services/
    ├── adb_client.py               # AdbManager 单例：tap/swipe/text/keyevent + 外部设备
    ├── docker_manager.py           # DockerManager 单例：spawn/delete/list/resize Redroid
    ├── scrcpy_track.py             # ScrcpyTrack (MediaStreamTrack)：4 阶段视频捕获
    └── webrtc_manager.py           # WebRTCManager 单例：SDP Offer/Answer + MediaRelay
```

#### 服务详解

**AdbManager (`adb_client.py`)**:

| 方法 | 说明 |
|------|------|
| `tap(container_id, x, y)` | 点击坐标 |
| `swipe(x1,y1,x2,y2,duration)` | 滑动 |
| `input_text(text)` | 文本输入（自动转义） |
| `keyevent(keycode)` | 按键（26=电源, 4=返回, 3=主页） |
| `tap_with_conversion()` | 带 Scrcpy→屏幕坐标转换的点击 |
| `long_press()` | 1000ms 同点滑动模拟长按 |
| `register_external_device()` | 注册外部 ADB 设备（支持 RSA 密钥） |
| `get_screen_size()` | 获取物理分辨率（`wm size`） |
| `install_apk()` / `install_xapk()` | APK/XAPK 安装（含 3 策略 XAPK） |

- 内部：`_execute()` 用 `adb_shell` 库；外部设备回退到 `adb` CLI（支持 TLS MIUI）
- 连接缓存：`_devices[container_id]` 复用连接
- 锁机制：`_locks[container_id]` 防止并发握手冲突
- 坐标转换：处理 4 种旋转/比例场景

**DockerManager (`docker_manager.py`)**:

| 方法 | 说明 |
|------|------|
| `spawn_redroid(width,height,fps,device_model)` | 创建 Redroid 13.0 容器，自动分配端口 5555-5600 |
| `delete_container(id, force)` | 强制删除 |
| `list_containers()` | 列出 redroid 容器 |
| `resize_container(id,w,h,fps,model)` | 删除重建（保持端口不变） |

- Redroid 镜像：`redroid/redroid:13.0.0-latest`
- 端口分配：`asyncio.Lock` 防止竞态，扫描 5555-5600 可用端口
- 容器配置：`--privileged`，bridge 网络，shm_size=2g，Android boot args

**ScrcpyTrack (`scrcpy_track.py`)**:

4 阶段连接流程：

```
Phase 1: adb push scrcpy-server + adb forward tcp:<port> localabstract:scrcpy
Phase 2: adb shell CLASSPATH=... app_process / com.genymobile.scrcpy.Server 3.3.4
Phase 3: 连接 forward 端口，读取 77 字节握手
         ┌────────┬──────────────────────┬──────────┬─────────────┬─────────────┐
         │ 1 Byte │ 64 Bytes (设备名 UTF-8) │ 4 Bytes  │ 4 Bytes (BE)│ 4 Bytes(BE) │
         │ Dummy  │                      │ Codec ID │ Width        │ Height       │
         └────────┴──────────────────────┴──────────┴─────────────┴─────────────┘
Phase 4: av.CodecContext.create(codec_id, 'r') 初始化解码器
```

视频帧格式（v3.x）：
```
┌─────────────────┬───────────────┬────────────────────┐
│ 8 Bytes PTS (BE)│ 4 Bytes Size  │ N Bytes H.264       │
│ PTS MSB=1: 配置包│               │ SPS/PPS 或视频帧    │
│ PTS MSB=0: 视频帧│               │                    │
└─────────────────┴───────────────┴────────────────────┘
```

视频质量预设：

| 级别 | max_size | 码率 |
|------|----------|------|
| High | 720 | 2.5 Mbps |
| Medium | 480 | 1.5 Mbps |
| Low | 360 | 800 Kbps |

**WebRTCManager (`webrtc_manager.py`)**:

- `MediaRelay` 复用：一个 ScrcpyTrack 被多个 RTCPeerConnection 共享
- STUN：小米 + B站（国内可用）
- `aioice` monkey patch：修复 Docker 中 `ifaddr` 返回空列表导致 UDP 绑定失败
- Safari 兼容：SDP 注入视频 m-line，移除 `goog-remb`/`transport-cc` 等不兼容 rtcp-fb
- DataChannel 并发执行：无锁，指令立即创建 `asyncio.create_task()`

---

## 4. API 参考

### 4.1 认证接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/auth/login` | POST | 邮箱密码登录，返回 JWT | 否 |
| `/api/auth/register` | POST | 注册用户，自动创建配额 | 否 |

### 4.2 用户接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/users/me` | GET | 当前用户信息 | User |
| `/api/users/me/quota` | GET | 当前用户配额 | User |
| `/api/users/admin/users` | GET | 管理员：用户列表 | Admin |
| `/api/users/admin/users/{id}` | PUT | 管理员：更新用户 | Admin |
| `/api/users/admin/users/{id}/quota` | PUT | 管理员：设置配额 | Admin |
| `/api/users/admin/stats` | GET | 管理员：统计 | Admin |

### 4.3 容器接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/instances` | GET | 所有实例列表（容器+外部设备） | User |
| `/api/containers/spawn` | POST | 创建容器（检查配额） | User |
| `/api/containers/{id}` | DELETE | 删除容器 | User |
| `/api/containers/{id}/resize` | POST | 调整分辨率 | User |
| `/api/containers/{id}/adb_port` | GET | 获取 ADB 端口 | User |

### 4.4 流媒体接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/stream/webrtc/offer` | POST | WebRTC SDP Offer，返回 Answer | User |
| `/api/stream/quality` | POST | 切换视频质量（high/medium/low） | User |
| `/api/stream/stats/{id}` | GET | 连接统计（码率/RTT/丢包） | User |

### 4.5 控制接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/action/click` | POST | 点击 (x, y) | User |
| `/api/action/swipe` | POST | 滑动 (x1,y1→x2,y2,duration) | User |
| `/api/action/text` | POST | 文本输入 | User |
| `/api/action/keyevent` | POST | 按键事件 (keycode) | User |

### 4.6 外部设备接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/external-devices` | POST | 添加外部设备 | User |
| `/api/external-devices` | GET | 列出外部设备 | User |
| `/api/external-devices/{uuid}` | PUT | 更新设备信息 | User |
| `/api/external-devices/{uuid}` | DELETE | 删除设备记录 | User |
| `/api/external-devices/pair` | POST | ADB 无线配对（MIUI） | User |
| `/api/external-devices/test-direct` | POST | 测试直连 | User |
| `/api/external-devices/{uuid}/test` | POST | 测试已有设备 | User |

### 4.7 其他接口

| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| `/api/apk/install` | POST | 安装 APK/XAPK（multipart, 500MB） | User |
| `/api/agents/register` | POST | Agent 注册 | 否 |
| `/api/agents/heartbeat` | POST | Agent 心跳 | 否 |
| `/api/agents/list` | GET | Agent 列表 | User |
| `/health` | GET | 健康检查 | 否 |

---

## 5. 部署架构

### 5.1 分布式部署（推荐）

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户网络                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Frontend (Next.js) :3000                            │
│              Backend (FastAPI) :8000                             │
│                                                                 │
│  Backend ────────────────────────────── Agent A (192.168.1.101)    │
│  (聚合实例)                               Agent B (192.168.1.102)  │
│              ────────────────────────── Agent C (192.168.1.103)   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   Redroid 容器           Redroid 容器         外部 Android 手机
   ADB :5555→5555        ADB :5555→5556        MIUI 无线调试
   Scrcpy H.264          Scrcpy H.264          RSA 密钥认证
```

### 5.2 docker-compose.yml（主部署）

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    environment:
      - DOCKER_HOST=unix:///var/run/docker.sock
      - OUTLAND_DB_URL=sqlite+aiosqlite:////app/data/outland.db
      - OUTLAND_JWT_SECRET=${JWT_SECRET}
      - OUTLAND_CORS_ORIGINS=${CORS_ORIGINS}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - backend-data:/app/data          # SQLite 数据库持久化

  frontend:
    build: ./frontend
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    depends_on:
      - backend

volumes:
  backend-data:                         # gitignored，存储 outland.db
```

### 5.3 Agent docker-compose.yml

```yaml
services:
  agent:
    build: ./agent
    network_mode: host                  # 必须 host 网络（WebRTC UDP）
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./agent-adb-keys:/root/.android  # ADB RSA 密钥持久化
    environment:
      - BACKEND_URL=http://192.168.1.100:8000
      - AGENT_ADVERTISED_URL=http://192.168.1.101:9090
      - REDROID_HOST=127.0.0.1
      - ADB_SERVER_HOST=127.0.0.1
      - ADB_SERVER_PORT=5037
```

---

## 6. 开发指南

### 6.1 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/your-repo/outland.git
cd outland

# 2. 启动后端（需要 Python 3.11+）
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 3. 启动 Agent（另一终端，需要 Docker）
cd agent
pip install -r requirements.txt
bash start_adb.sh &
python main.py                          # http://localhost:9090

# 4. 启动前端（另一终端，需要 Node.js 18+）
cd frontend
npm install
npm run dev                             # http://localhost:3000
```

### 6.2 目录结构

```
outland/
├── docker-compose.yml           # 主部署：Backend + Frontend
├── setup-redroid.sh             # Redroid 一键部署脚本（内核模块 + 防火墙）
├── readme.md                    # 本文档（中文）
├── README_EN.md                 # English version
│
├── backend/                     # FastAPI 后端
│   ├── main.py                  # 入口，10 个路由注册
│   ├── auth/                    # JWT + bcrypt 认证
│   ├── core/                    # 配置 + httpx 客户端
│   ├── database/                # SQLAlchemy 异步 ORM
│   ├── middleware/              # 日志 + 异常中间件
│   ├── models/                  # Pydantic 请求/响应模型
│   ├── routers/                 # 10 个 API 路由
│   └── services/                # Agent Registry 服务
│
├── agent/                       # Agent 边缘节点
│   ├── main.py                  # 入口，14 个端点
│   ├── services/
│   │   ├── adb_client.py        # ADB 控制（tap/swipe/text/keyevent）
│   │   ├── docker_manager.py    # Redroid 容器管理
│   │   ├── scrcpy_track.py      # Scrcpy v3.3.4 协议实现
│   │   └── webrtc_manager.py    # WebRTC + MediaRelay
│   ├── docker-compose.yml        # Agent + Redroid 编排
│   └── start_adb.sh             # ADB Server 启动脚本
│
└── frontend/                    # Next.js 前端
    ├── app/
    │   ├── page.tsx             # Dashboard
    │   ├── login/page.tsx      # 登录注册
    │   └── player/[id]/page.tsx # WebRTC Player
    ├── components/
    │   ├── WebRTCPlayer.tsx     # 播放器组件
    │   └── ApkUploader.tsx      # APK 上传
    └── lib/api.ts               # API 封装
```

### 6.3 环境变量

#### Backend (.env)

```bash
OUTLAND_DB_URL=sqlite+aiosqlite:////app/data/outland.db
OUTLAND_JWT_SECRET=change-me-in-production
OUTLAND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
OUTLAND_DEBUG=false
```

#### Agent (.env)

```bash
BACKEND_URL=http://192.168.1.100:8000
AGENT_ADVERTISED_URL=http://192.168.1.101:9090
AGENT_ID=agent-node-01
ADB_SERVER_HOST=127.0.0.1
ADB_SERVER_PORT=5037
REDROID_HOST=127.0.0.1
REDROID_ADB_PORT=5555
SCRCPY_SERVER_PATH=/usr/local/bin/scrcpy-server
SCRCPY_ENCODER_TYPE=hardware
```

---

## 7. 技术亮点

### 7.1 Scrcpy v3.3.4 协议纯 Python 实现

`scrcpy_track.py` 完整实现 Scrcpy v3.x 协议：
- 4 阶段连接（推送服务端 → 建立隧道 → Socket 握手 → 视频流解析）
- PyAV 解码 H.264/VP8/VP9/AV1
- 77 字节握手协议解析（设备名/Codec ID/分辨率）
- 12 字节帧头解析（PTS + Size + H.264 数据）
- 动态端口分配（27183+counter）避免多设备冲突

### 7.2 WebRTC 视频流复用

`webrtc_manager.py` 使用 `aiortc` + `MediaRelay`：
- 一个 ScrcpyTrack 同时服务多个 RTCPeerConnection
- DataChannel 并发指令执行，无锁设计
- ICE gathering 5 秒超时控制
- 连接统计（码率/RTT/丢包率）实时采集

### 7.3 ADB 异步控制

`adb_client.py` 基于 `adb-shell[async]`：
- 连接缓存复用，`asyncio.Lock` 防并发握手冲突
- 坐标自动转换（Scrcpy 视频坐标 → 物理屏幕坐标）
- 外部设备支持 RSA 密钥文件 + CLI 回退（MIUI TLS）
- XAPK 3 策略安装（shared libs first / all together / non-libs first）

### 7.4 Safari WebRTC 兼容性

解决 Safari 不发送视频 m-line 的问题：
- Canvas 假视频轨道触发 SDP 包含视频
- SDP 清理：移除 `goog-remb`/`transport-cc`/`ccm fir` 等不兼容参数
- 远端 SDP 修复：确保 video m-line 存在

### 7.5 NAT 穿透

国内可用 STUN 服务器：
```
stun:stun.miwifi.com:3478      # 小米
stun:stun.chat.bilibili.com:3478 # B站
```

---

## 8. 常见问题

### Q: Redroid 容器无法启动？

```bash
# 检查内核模块
lsmod | grep binder
# 加载 binder（需要 root）
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
# 或使用一键脚本
sudo ./setup-redroid.sh
```

### Q: WebRTC 连接失败？

1. 检查防火墙 UDP 端口（1024-65535 范围 WebRTC 会随机选端口）
2. 确认 STUN 服务器可达
3. Agent 必须使用 `network_mode: host`
4. 查看 Agent 日志确认 Scrcpy 握手状态

### Q: 外部设备连接失败？

1. MIUI 设备：先使用配对码配对（`/api/external-devices/pair`）
2. 检查 ADB 无线调试是否开启（开发者选项 → 无线调试）
3. 确认 RSA 密钥已授信（弹框确认后重启 adbd）
4. 检查端口是否被防火墙拦截

### Q: Agent 无法连接 Backend？

确认网络可达：
```bash
curl http://192.168.1.100:8000/health
```
检查 Agent 日志中的 `BACKEND_URL` 是否正确。

### Q: XAPK 安装失败？

XAPK 安装有 3 种策略：先装 shared libs、先装非 libs、全量一起。均失败时可能是 split APK 包含 `.so` native 库但路径解析错误，需要设备端 ADB daemon 权限。

---

## 9. 参考资料

- [Redroid 官方文档](https://github.com/remoteAndroid/redroid)
- [Scrcpy 协议文档](https://github.com/Genymobile/scrcpy)
- [aiortc 文档](https://aiortc.readthedocs.io/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Next.js 文档](https://nextjs.org/docs)
- [PyAV 文档](https://pyav.org/docs/stable/)
- [SQLAlchemy 异步文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)

---

## 10. 开源协议

本项目基于 [MIT 协议](LICENSE) 开源。
