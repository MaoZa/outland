# Outland - Android Cloud Container Platform

> An open-source platform for self-hosted Android 13 cloud gaming streaming and automation control. Runs full Android systems in Docker via Redroid, with WebRTC-based low-latency real-time video streaming and remote control.

---

## 1. Project Overview

### 1.1 Core Features

| Feature | Description |
|---------|-------------|
| Docker-based Android | Full Android 13 via Redroid 13.0 in Docker with privileged mode |
| Cloud Gaming Streaming | WebRTC + Scrcpy protocol, <200ms latency real-time video |
| Remote Control | Async ADB control: tap, swipe, text input, key events |
| Script Automation | RESTful API for automation integration |
| External Device Support | Connect real Android phones; MIUI wireless debugging pairing |
| Multi-Agent Architecture | Distributed deployment; Backend aggregates containers from multiple Agents |
| User Authentication | JWT + bcrypt auth with user quota management |
| Video Quality Control | High (720p/2.5Mbps) / Medium (480p/1.5Mbps) / Low (360p/800Kbps) |
| APK/XAPK Installation | Single APK and XAPK support (split APK + shared libraries) |
| Container Resize | Dynamic resolution and FPS adjustment without data loss |
| Safari Compatibility | Auto video m-line injection, Safari WebRTC SDP compatibility |

### 1.2 Technology Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| **Infrastructure** | Redroid 13.0 (Android in Docker) | Containerized Android, privileged mode |
| **Backend** | Python 3.11 + FastAPI + Pydantic v2 | API gateway, async architecture |
| **Database** | SQLAlchemy + aiosqlite (SQLite) | Async ORM, User/Container/Quota persistence |
| **Authentication** | PyJWT + bcrypt | HS256 tokens, 24h expiry |
| **Container Control** | Docker SDK for Python (async) | Redroid lifecycle management |
| **Automation Control** | adb-shell[async] + CLI fallback | Tap/swipe/input, TLS external device support |
| **Streaming** | Scrcpy v3.3.4 + aiortc + PyAV 12.3.0 | Video capture + WebRTC real-time streaming |
| **Frontend** | Next.js 14 + TailwindCSS + Lucide | SSR + responsive UI |

### 1.3 System Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          User Browser                                        │
│                 WebRTC Video Stream + DataChannel Control                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTPS/HTTP
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js) :3000                              │
│  ┌─────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐ │
│  │  Login/Register │  │  Instance List + Ext.  │  │  WebRTC Player        │ │
│  │  Auth Guard     │  │  Create/Delete/Resize │  │  Video + Control      │ │
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
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐         │
│  │ /health │ │ /api/   │ │ /api/    │ │ /api/    │ │ /api/       │         │
│  │ Health  │ │ auth    │ │ users    │ │ agents   │ │ external-   │         │
│  │         │ │ Login   │ │ Quotas   │ │ Register │ │ devices     │         │
│  └─────────┘ └─────────┘ └──────────┘ └──────────┘ └─────────────┘         │
│                                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐       │
│  │ /api/    │ │ /api/    │ │ /api/    │ │ /api/    │ │ /api/apk     │       │
│  │ instances │ │ containers│ │ stream   │ │ action   │ │ Install APK │       │
│  │ Aggregate │ │ Manage   │ │ WebRTC   │ │ Control  │ │              │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────┘       │
│                                    │                                        │
│                    ┌───────────────┴───────────────┐                        │
│                    ▼                               ▼                        │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │  Agent Registry (In-Memory) │  │  SQLite Database (Async)            │  │
│  │  { agent_id: url, heartbeat }│  │  User / Container / Quota          │  │
│  │  180s timeout cleanup       │  │  ExternalDevice / AgentState        │  │
│  └─────────────────────────────┘  └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP / WebSocket
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────────────┐
│   Agent A (:9090)   │  │   Agent B (:9090)   │  │   Agent C (:9090)          │
│   Host 192.168.1.101  │  │   Host 192.168.1.102  │  │   Host 192.168.1.103        │
│                     │  │                     │  │                             │
│  ┌────────────────┐ │  ┌────────────────┐ │  │  External Device (MIUI)    │ │
│  │ Redroid Container│ │  │ Redroid Container│ │  │  ADB tcp:192.168.1.100  │ │
│  │ ADB :5555→5555 │ │  │ ADB :5555→5556 │ │  │  RSA Key Auth            │ │
│  │                 │ │  │                │ │  │  ADB Pair + Connect      │ │
│  │ Scrcpy Server   │ │  │ Scrcpy Server │ │  │                          │ │
│  │ H.264 Stream    │ │  │ H.264 Stream  │ │  │                          │ │
│  └────────────────┘ │  └────────────────┘ │  └────────────────────────────┘ │
└─────────────────────┘  └─────────────────────┘  └─────────────────────────────┘
```

---

## 2. Database Models

### 2.1 ER Diagram

```
User (1) ─────< Quota (1)
    │
    └────< Container (N)       Container ────> Agent (N:1, via agent_id)
    │
    └────< ExternalDevice (N)  ExternalDevice ───> Agent (N:1, via agent_id)

AgentState (standalone record, for future persistence; in-memory Registry used currently)
```

### 2.2 Model Details

| Model | Table | Key Fields | Notes |
|-------|-------|------------|-------|
| **User** | `users` | id, email (unique), hashed_password, is_admin, is_active, is_verified | Auth |
| **Quota** | `quotas` | user_id (FK, unique), max_containers (default=1) | Per-user container limit |
| **Container** | `containers` | uuid, user_id (FK), agent_id, container_id, status, resolution, created_at | Container record |
| **ExternalDevice** | `external_devices` | uuid, user_id (FK), agent_id, name, adb_host, adb_port, rsa_key_path, status, resolution | External device |
| **AgentState** | `agent_states` | agent_id (unique), url, last_heartbeat | Persistence backup for Registry |

---

## 3. Module Details

### 3.1 Frontend

**Tech Stack**: Next.js 14 + React 18 + TailwindCSS + Lucide Icons + TypeScript

#### Directory Structure

```
frontend/
├── app/
│   ├── page.tsx                    # Dashboard: instance list + create/delete/ext. devices
│   ├── layout.tsx                  # Root layout + AuthGuard
│   ├── auth-guard.tsx              # Auth guard: redirect to /login if not authenticated
│   ├── login/page.tsx             # Login/Register
│   └── player/[id]/page.tsx        # WebRTC Player: video + control
├── components/
│   ├── WebRTCPlayer.tsx            # Core player: WebRTC + DataChannel + coordinate mapping
│   └── ApkUploader.tsx            # APK/XAPK upload and install
└── lib/
    ├── api.ts                      # All API calls (60+ functions)
    └── auth.tsx                    # AuthContext: login/logout/state
```

#### Core Features

**Dashboard (`page.tsx`)**:
- `InstanceCard` — Differentiates local containers (source≠'external') vs external devices (blue Wifi icon + "Remote" badge)
- `AddExternalDeviceModal` — 3-step wizard: ①Pair ②Connect test ③Save (includes MIUI pairing code)
- `CreateContainerModal` — Agent selection + resolution presets (low/high/landscape)
- `ResizeModal` — Container resolution adjustment
- `DeleteConfirmModal` — Delete confirmation (external devices only remove record, real device unaffected)

**WebRTCPlayer (`WebRTCPlayer.tsx`)**:
- Creates RTCPeerConnection (STUN: miwifi.com, bilibili.com)
- DataChannel 'control' sends JSON commands (click/swipe/input/keyevent/long_press)
- Coordinate mapping: `clientToAndroid()` handles 4 rotation/scale cases
- Safari compatibility: Canvas fake video track ensures m-line exists
- Quality switching: Reconnects with high/medium/low level

**API Proxy (next.config.js)**:
- 22 rewrite rules, all `/api/*` forwarded to `backend:8000`
- `/api/external-devices/:path*` wildcard matching

---

### 3.2 Backend

**Tech Stack**: Python 3.11 + FastAPI 0.109+ + Pydantic v2 + SQLAlchemy async + httpx

#### Directory Structure

```
backend/
├── main.py                         # FastAPI entry, 10 routers registered, lifespan management
├── requirements.txt                # Dependencies
│
├── auth/                           # Auth module
│   ├── jwt.py                      # create_access_token / verify_token (HS256, 24h)
│   ├── password.py                 # hash_password / verify_password (bcrypt)
│   └── dependencies.py             # get_current_user / require_admin (FastAPI Depends)
│
├── core/                           # Core config
│   ├── config.py                   # Pydantic Settings, OUTLAND_* env prefix
│   └── http_client.py               # httpx.AsyncClient singleton (HTTP/2, 100 connections)
│
├── database/                        # Database layer
│   ├── models.py                   # SQLAlchemy ORM: User/Container/Quota/ExternalDevice
│   └── __init__.py                 # engine / async_session_maker / get_db() / init_db()
│
├── middleware/                      # Middleware
│   ├── logging.py                  # RequestLoggingMiddleware (structlog)
│   └── exception_handler.py          # ExceptionHandlerMiddleware → 500 JSON
│
├── models/                          # Pydantic Schema
│   ├── agent.py                    # AgentRegister/Heartbeat/Info/RegistryResponse
│   ├── container.py                # PortMapping/ContainerInfo/SpawnRequest/ResizeRequest
│   ├── external_device.py          # ExternalDeviceCreate/Update/Response/TestResponse
│   ├── stream.py                   # WebRTCOffer/QualityChange/ConnectionStats
│   ├── action.py                   # Click/Swipe/Text/KeyEvent/ActionResponse
│   └── apk.py                      # ApkInstallResponse
│
├── routers/                         # API Routes
│   ├── health.py                   # GET /, GET /health
│   ├── auth/__init__.py             # POST /api/auth/login, /register
│   ├── users.py                    # GET /api/users/me, PUT /api/users/admin/*
│   ├── agents.py                   # POST /api/agents/register, /heartbeat
│   ├── instances.py                # GET /api/instances (aggregates all Agent containers)
│   ├── containers.py               # POST /api/containers/spawn, DELETE /{id}, POST /{id}/resize
│   ├── stream.py                   # POST /api/stream/webrtc/offer, /quality, GET /stats/{id}
│   ├── actions.py                  # POST /api/action/click|swipe|text|keyevent
│   ├── apk.py                      # POST /api/apk/install
│   ├── external_devices.py         # CRUD + /pair + /test-direct
│   └── external_device_helpers.py  # is_external_device / get_external_device / resolve_agent
│
└── services/
    └── agent_registry.py            # AGENT_REGISTRY in-memory dict + cleanup_loop + fetch_agent_instances
```

#### Middleware Stack (add order, outer first)

```
1. CORSMiddleware              ← CORS, allows OUTLAND_CORS_ORIGINS
2. SlowAPIMiddleware           ← Global rate limiting
3. ExceptionHandlerMiddleware   ← Uncaught exceptions → 500 JSON
4. RequestLoggingMiddleware     ← structlog: method, path, status, duration_ms
```

#### Environment Variables (`OUTLAND_` prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | "Outland Backend" | Application name |
| `DEBUG` | False | SQLAlchemy echo |
| `HOST` / `PORT` | 0.0.0.0 / 8000 | Bind address |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/outland.db` | DB connection |
| `JWT_SECRET` | "change-me-in-production" | HS256 signing key |
| `JWT_ALGORITHM` | "HS256" | Algorithm |
| `HEARTBEAT_TIMEOUT` | 180 | Agent heartbeat timeout (seconds) |
| `HEARTBEAT_CLEANUP_INTERVAL` | 60 | Cleanup interval (seconds) |
| `HTTP_MAX_KEEPALIVE` | 20 | httpx keepalive connections |
| `HTTP_MAX_CONNECTIONS` | 100 | httpx max connections |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed origins |

---

### 3.3 Agent

**Tech Stack**: Python 3.11 + FastAPI + aiortc + PyAV 12.3.0 + adb-shell + Docker SDK

#### Directory Structure

```
agent/
├── main.py                         # FastAPI entry, 14 endpoints, lifespan heartbeat
├── requirements.txt                # Dependencies
├── Dockerfile                      # Image: python:3.11 + FFmpeg + build-essential + scrcpy v3.3.4
├── docker-compose.yml              # host network mode + adb-keys persistent volume
├── start_adb.sh                    # ADB Server startup script
├── .env                            # BACKEND_URL / AGENT_ADVERTISED_URL / REDROID_HOST
│
└── services/
    ├── adb_client.py               # AdbManager singleton: tap/swipe/text/keyevent + ext. devices
    ├── docker_manager.py           # DockerManager singleton: spawn/delete/list/resize Redroid
    ├── scrcpy_track.py             # ScrcpyTrack (MediaStreamTrack): 4-phase video capture
    └── webrtc_manager.py            # WebRTCManager singleton: SDP Offer/Answer + MediaRelay
```

#### Service Details

**AdbManager (`adb_client.py`)**

| Method | Description |
|--------|-------------|
| `tap(container_id, x, y)` | Tap at coordinates |
| `swipe(x1,y1,x2,y2,duration)` | Swipe gesture |
| `input_text(text)` | Text input (auto-escaped) |
| `keyevent(keycode)` | Key event (26=POWER, 4=BACK, 3=HOME) |
| `tap_with_conversion()` | Tap with Scrcpy→screen coordinate conversion |
| `long_press()` | 1000ms same-point swipe to simulate long press |
| `register_external_device()` | Register external ADB device (RSA key support) |
| `get_screen_size()` | Get physical resolution (`wm size`) |
| `install_apk()` / `install_xapk()` | APK/XAPK install (3-strategy XAPK) |

- Internal: `_execute()` uses `adb_shell` library; external devices fall back to `adb` CLI (TLS MIUI support)
- Connection cache: `_devices[container_id]` reuses connections
- Lock mechanism: `_locks[container_id]` prevents concurrent handshake collisions
- Coordinate conversion: handles 4 rotation/scale scenarios

**DockerManager (`docker_manager.py`)**

| Method | Description |
|--------|-------------|
| `spawn_redroid(width,height,fps,device_model)` | Create Redroid 13.0 container, auto-allocates port 5555-5600 |
| `delete_container(id, force)` | Force delete |
| `list_containers()` | List redroid containers |
| `resize_container(id,w,h,fps,model)` | Delete and recreate (preserves port) |

- Redroid image: `redroid/redroid:13.0.0-latest`
- Port allocation: `asyncio.Lock` prevents race, scans 5555-5600 for available ports
- Container config: `--privileged`, bridge network, shm_size=2g, Android boot args

**ScrcpyTrack (`scrcpy_track.py`)**

4-phase connection:

```
Phase 1: adb push scrcpy-server + adb forward tcp:<port> localabstract:scrcpy
Phase 2: adb shell CLASSPATH=... app_process / com.genymobile.scrcpy.Server 3.3.4
Phase 3: Connect to forward port, read 77-byte handshake
         ┌────────┬──────────────────────┬──────────┬─────────────┬─────────────┐
         │ 1 Byte │ 64 Bytes (Device Name UTF-8)│ 4 Bytes │ 4 Bytes (BE)│ 4 Bytes(BE)│
         │ Dummy  │                      │ Codec ID │ Width        │ Height       │
         └────────┴──────────────────────┴──────────┴─────────────┴─────────────┘
Phase 4: av.CodecContext.create(codec_id, 'r') initialize decoder
```

Video frame format (v3.x):
```
┌─────────────────┬───────────────┬────────────────────┐
│ 8 Bytes PTS (BE)│ 4 Bytes Size │ N Bytes H.264      │
│ PTS MSB=1: config│              │ SPS/PPS or video    │
│ PTS MSB=0: frame │              │                    │
└─────────────────┴───────────────┴────────────────────┘
```

Video quality presets:

| Level | max_size | Bitrate |
|-------|----------|---------|
| High | 720 | 2.5 Mbps |
| Medium | 480 | 1.5 Mbps |
| Low | 360 | 800 Kbps |

**WebRTCManager (`webrtc_manager.py`)**

- `MediaRelay`: One ScrcpyTrack shared by multiple RTCPeerConnections
- STUN: Xiaomi + Bilibili (China-accessible)
- `aioice` monkey patch: Fixes Docker UDP binding failure when `ifaddr` returns empty adapter list
- Safari compatibility: SDP video m-line injection, removes incompatible `goog-remb`/`transport-cc` rtcp-fb params
- DataChannel concurrent execution: No lock, commands immediately create `asyncio.create_task()`

---

## 4. API Reference

### 4.1 Auth Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/auth/login` | POST | Email/password login, returns JWT | None |
| `/api/auth/register` | POST | Register user, auto-creates quota | None |

### 4.2 User Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/users/me` | GET | Current user info | User |
| `/api/users/me/quota` | GET | Current user quota | User |
| `/api/users/admin/users` | GET | Admin: user list | Admin |
| `/api/users/admin/users/{id}` | PUT | Admin: update user | Admin |
| `/api/users/admin/users/{id}/quota` | PUT | Admin: set quota | Admin |
| `/api/users/admin/stats` | GET | Admin: statistics | Admin |

### 4.3 Container Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/instances` | GET | All instance list (containers + external devices) | User |
| `/api/containers/spawn` | POST | Create container (quota check) | User |
| `/api/containers/{id}` | DELETE | Delete container | User |
| `/api/containers/{id}/resize` | POST | Adjust resolution | User |
| `/api/containers/{id}/adb_port` | GET | Get ADB port | User |

### 4.4 Streaming Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/stream/webrtc/offer` | POST | WebRTC SDP Offer, returns Answer | User |
| `/api/stream/quality` | POST | Switch video quality (high/medium/low) | User |
| `/api/stream/stats/{id}` | GET | Connection stats (bitrate/RTT/packet loss) | User |

### 4.5 Action Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/action/click` | POST | Tap at (x, y) | User |
| `/api/action/swipe` | POST | Swipe (x1,y1→x2,y2,duration) | User |
| `/api/action/text` | POST | Text input | User |
| `/api/action/keyevent` | POST | Key event (keycode) | User |

### 4.6 External Device Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/external-devices` | POST | Add external device | User |
| `/api/external-devices` | GET | List external devices | User |
| `/api/external-devices/{uuid}` | PUT | Update device info | User |
| `/api/external-devices/{uuid}` | DELETE | Delete device record | User |
| `/api/external-devices/pair` | POST | ADB wireless pairing (MIUI) | User |
| `/api/external-devices/test-direct` | POST | Test direct connection | User |
| `/api/external-devices/{uuid}/test` | POST | Test existing device | User |

### 4.7 Other Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/apk/install` | POST | Install APK/XAPK (multipart, 500MB) | User |
| `/api/agents/register` | POST | Agent registration | None |
| `/api/agents/heartbeat` | POST | Agent heartbeat | None |
| `/api/agents/list` | GET | Agent list | User |
| `/health` | GET | Health check | None |

---

## 5. Deployment Architecture

### 5.1 Distributed Deployment (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Network                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Frontend (Next.js) :3000                            │
│              Backend (FastAPI) :8000                             │
│                                                                 │
│  Backend ────────────────────────────── Agent A (192.168.1.101)   │
│  (aggregates instances)                    Agent B (192.168.1.102) │
│              ────────────────────────── Agent C (192.168.1.103)   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   Redroid Container      Redroid Container     External Android Phone
   ADB :5555→5555       ADB :5555→5556       MIUI Wireless Debugging
   Scrcpy H.264          Scrcpy H.264         RSA Key Auth
```

### 5.2 docker-compose.yml (Main Deployment)

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
      - backend-data:/app/data          # SQLite database persistence

  frontend:
    build: ./frontend
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    depends_on:
      - backend

volumes:
  backend-data:                         # gitignored, stores outland.db
```

### 5.3 Agent docker-compose.yml

```yaml
services:
  agent:
    build: ./agent
    network_mode: host                  # Required for WebRTC UDP
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./agent-adb-keys:/root/.android  # ADB RSA key persistence
    environment:
      - BACKEND_URL=http://192.168.1.100:8000
      - AGENT_ADVERTISED_URL=http://192.168.1.101:9090
      - REDROID_HOST=127.0.0.1
      - ADB_SERVER_HOST=127.0.0.1
      - ADB_SERVER_PORT=5037
```

---

## 6. Development Guide

### 6.1 Quick Start

```bash
# 1. Clone the project
git clone https://github.com/your-repo/outland.git
cd outland

# 2. Start Backend (requires Python 3.11+)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 3. Start Agent (another terminal, requires Docker)
cd agent
pip install -r requirements.txt
bash start_adb.sh &
python main.py                          # http://localhost:9090

# 4. Start Frontend (another terminal, requires Node.js 18+)
cd frontend
npm install
npm run dev                             # http://localhost:3000
```

### 6.2 Directory Structure

```
outland/
├── docker-compose.yml           # Main deployment: Backend + Frontend
├── setup-redroid.sh              # Redroid one-click deployment (kernel modules + firewall)
├── readme.md                    # This document (Chinese)
├── README_EN.md                 # English version
│
├── backend/                     # FastAPI backend
│   ├── main.py                  # Entry, 10 routers registered
│   ├── auth/                    # JWT + bcrypt authentication
│   ├── core/                    # Config + httpx client
│   ├── database/                # SQLAlchemy async ORM
│   ├── middleware/             # Logging + exception middleware
│   ├── models/                  # Pydantic request/response models
│   ├── routers/                 # 10 API routers
│   └── services/                # Agent Registry service
│
├── agent/                       # Agent edge node
│   ├── main.py                  # Entry, 14 endpoints
│   ├── services/
│   │   ├── adb_client.py        # ADB control (tap/swipe/text/keyevent)
│   │   ├── docker_manager.py    # Redroid container management
│   │   ├── scrcpy_track.py      # Scrcpy v3.3.4 protocol implementation
│   │   └── webrtc_manager.py    # WebRTC + MediaRelay
│   ├── docker-compose.yml        # Agent + Redroid orchestration
│   └── start_adb.sh            # ADB Server startup script
│
└── frontend/                    # Next.js frontend
    ├── app/
    │   ├── page.tsx             # Dashboard
    │   ├── login/page.tsx      # Login/Register
    │   └── player/[id]/page.tsx # WebRTC Player
    ├── components/
    │   ├── WebRTCPlayer.tsx     # Player component
    │   └── ApkUploader.tsx      # APK uploader
    └── lib/api.ts               # API wrapper
```

### 6.3 Environment Variables

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

## 7. Technical Highlights

### 7.1 Scrcpy v3.3.4 Protocol Pure Python Implementation

`scrcpy_track.py` fully implements Scrcpy v3.x protocol:
- 4-phase connection (push server → establish tunnel → Socket handshake → video stream parsing)
- PyAV decodes H.264/VP8/VP9/AV1
- 77-byte handshake protocol parsing (device name/Codec ID/resolution)
- 12-byte frame header parsing (PTS + Size + H.264 data)
- Dynamic port allocation (27183+counter) to avoid multi-device conflicts

### 7.2 WebRTC Video Stream Multiplexing

`webrtc_manager.py` uses `aiortc` + `MediaRelay`:
- One ScrcpyTrack serves multiple RTCPeerConnections simultaneously
- DataChannel concurrent command execution, lock-free design
- ICE gathering 5-second timeout control
- Connection statistics (bitrate/RTT/packet loss) real-time collection

### 7.3 ADB Async Control

`adb_client.py` based on `adb-shell[async]`:
- Connection cache reuse, `asyncio.Lock` prevents concurrent handshake collisions
- Automatic coordinate conversion (Scrcpy video coordinates → physical screen coordinates)
- External device support with RSA key file + CLI fallback (MIUI TLS)
- XAPK 3-strategy installation (shared libs first / all together / non-libs first)

### 7.4 Safari WebRTC Compatibility

Solves Safari not sending video m-line:
- Canvas fake video track triggers SDP to include video
- SDP cleanup: removes incompatible `goog-remb`/`transport-cc`/`ccm fir` params
- Remote SDP fix: ensures video m-line exists

### 7.5 NAT Traversal

China-accessible STUN servers:
```
stun:stun.miwifi.com:3478      # Xiaomi
stun:stun.chat.bilibili.com:3478 # Bilibili
```

---

## 8. FAQ

### Q: Redroid container fails to start?

```bash
# Check kernel modules
lsmod | grep binder
# Load binder (requires root)
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
# Or use one-click script
sudo ./setup-redroid.sh
```

### Q: WebRTC connection fails?

1. Check firewall UDP port range (1024-65535, WebRTC randomly selects)
2. Confirm STUN server is reachable
3. Agent must use `network_mode: host`
4. Check Agent logs for Scrcpy handshake status

### Q: External device connection fails?

1. MIUI devices: Pair first using pairing code (`/api/external-devices/pair`)
2. Check if ADB wireless debugging is enabled (Developer Options → Wireless Debugging)
3. Confirm RSA key is trusted (confirm popup then restart adbd)
4. Check if firewall is blocking the port

### Q: Agent cannot connect to Backend?

Confirm network connectivity:
```bash
curl http://192.168.1.100:8000/health
```
Check if `BACKEND_URL` in Agent logs is correct.

### Q: XAPK installation fails?

XAPK installation has 3 strategies: install shared libs first / install all together / install non-libs first. If all fail, it may be due to split APK containing `.so` native libraries with incorrect path resolution, requiring device-side ADB daemon permissions.

---

## 9. References

- [Redroid Documentation](https://github.com/remoteAndroid/redroid)
- [Scrcpy Protocol](https://github.com/Genymobile/scrcpy)
- [aiortc Documentation](https://aiortc.readthedocs.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Next.js Documentation](https://nextjs.org/docs)
- [PyAV Documentation](https://pyav.org/docs/stable/)
- [SQLAlchemy Async Documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)