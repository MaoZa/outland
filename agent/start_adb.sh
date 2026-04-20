#!/bin/bash
# Outland Agent ADB 启动脚本
# 在 uvicorn 启动前运行，确保 ADB Server 就绪
#
# 注意：新架构中 Redroid 容器是按需创建的，
# 不再在启动时等待特定设备。

set -e

ADB_HOST="${ADB_SERVER_HOST:-127.0.0.1}"
ADB_PORT="${ADB_SERVER_PORT:-5037}"

echo "[ADB] 启动 ADB Server (${ADB_HOST}:${ADB_PORT})..."

# 杀死可能存在的旧 ADB Server（本地模式）
adb kill-server 2>/dev/null || true
sleep 1

# 启动 ADB Server（使用 -L 指定监听地址为本地 TCP）
# 关键：使用 localabstract 或本地 TCP 模式启动，避免 "cannot start server on remote host"
adb -L tcp:5037 fork-server &
sleep 2

# 验证 ADB Server 是否启动成功
if adb devices 2>&1 | head -1 | grep -q "List of devices"; then
    echo "[ADB] ADB Server 已启动"
else
    echo "[ADB] 尝试备用启动方式..."
    # 备用：直接运行 adb start-server
    adb start-server
    echo "[ADB] ADB Server 已启动（备用方式）"
fi

echo "[ADB] ADB 初始化完成，容器将在需要时按需创建"

# 执行主命令
exec "$@"
