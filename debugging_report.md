# Outland WebRTC 流媒体问题诊断报告

## 项目概述

**项目名称**: Outland  
**项目描述**: Android 云容器平台，支持云游戏串流和脚本自动化  
**技术栈**:
- 底层: Redroid (Android 11 in Docker)
- 后端: Python (FastAPI) + aiortc (WebRTC)
- 容器控制: Docker SDK for Python + ADB
- 前端: Next.js (React) + TailwindCSS
- 流媒体: scrcpy → adb screenrecord

## 问题描述

**原始错误**: `ERROR: Could not create renderer: Couldn't find matching render driver`  
**根本原因**: scrcpy 需要 SDL2 图形渲染驱动，在无头 Docker 容器中无法工作。

---

## 尝试过的解决方案

### 方案 1: SDL_VIDEODRIVER=dummy ❌
修改 Dockerfile 添加 `ENV SDL_VIDEODRIVER=dummy`，仍然报错。

### 方案 2: 安装 SDL2 依赖包 ❌
安装 libsdl2-2.0-0、libsdl2-image-2.0-0 等包，scrcpy 仍无法运行。

### 方案 3: adb shell + screenrecord + ffmpeg ⚠️
使用 `adb shell screenrecord` 获取 H264 流，通过 ffmpeg 管道处理。
- PyAV 的 `av.open()` 卡住，无法读取数据
- 日志停在: `ffmpeg 已启动，正在等待视频数据...`

### 方案 4: adb exec-out + screenrecord ⚠️ (当前)
直接用 `adb exec-out screenrecord` 获取 H264，移除 ffmpeg。
- PyAV 的 `av.open()` 仍然卡住
- 日志停在: `screenrecord 正在运行，使用 PyAV 读取 H264 流...`

---

## 当前状态

```
[ScrcpyTrack] 使用 adb exec-out screenrecord 捕获屏幕...
[ScrcpyTrack] 等待 screenrecord 初始化...
[ScrcpyTrack] screenrecord 正在运行，使用 PyAV 读取 H264 流...
(卡住，无后续)
```

**前端错误**: `502 Bad Gateway` + `无法连接到远端 Agent`

---

## 技术分析

1. **ADB shell stdout 缓冲问题**: 通过 shell 传输二进制数据可能有问题
2. **ADB exec-out 可能不被 Redroid 支持**: 需要验证
3. **PyAV 管道读取兼容性**: PyAV 从 stdin 读取 H264 流可能遇到格式解析问题

---

## 待验证方案

### 方案 A: 文件中转方案 (推荐)
1. Android 启动 `screenrecord --output-format=h264 /sdcard/video.h264`
2. 每隔 N 秒拉取: `adb pull /sdcard/video.h264`
3. PyAV 读取文件

### 方案 B: 帧截图方案
1. 定期截图: `adb shell screencap -p > frame.png`
2. PIL 读取图片，PyAV 编码为 H264

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `agent/Dockerfile` | 容器配置 |
| `agent/services/scrcpy_track.py` | 视频轨道 (修改位置) |
| `agent/services/webrtc_manager.py` | WebRTC 管理器 |
| `agent/main.py` | FastAPI 主入口 |

---

## 调试命令

```bash
# 测试 exec-out (关键)
adb exec-out echo test

# 查看容器日志
docker logs -f agent

# 测试 screenrecord
adb -s localhost:5555 shell screenrecord --help
```

---

**报告生成时间**: 2026-04-20 12:38 CST
