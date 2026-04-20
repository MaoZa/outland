#!/bin/bash
# Outland Agent ADB 启动脚本
# 在 uvicorn 启动前运行，确保 ADB Server 和设备连接就绪

set -e

ADB_HOST="${ADB_SERVER_HOST:-127.0.0.1}"
ADB_PORT="${ADB_SERVER_PORT:-5037}"
REDROID_HOST="${REDROID_HOST:-127.0.0.1}"
REDROID_PORT="${REDROID_ADB_PORT:-5555}"

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

# 等待 redroid 就绪（通过检查端口）
echo "[ADB] 等待 redroid 设备就绪 (${REDROID_HOST}:${REDROID_PORT})..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    # 使用 nc 检查端口是否开放
    if timeout 1 bash -c "echo > /dev/tcp/${REDROID_HOST}/${REDROID_PORT}" 2>/dev/null; then
        echo "[ADB] redroid 端口已开放"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "[ADB] 等待 redroid... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "[ADB] 警告: redroid 未在超时内就绪，继续尝试连接..."
fi

# 连接 ADB 设备（带重试）
echo "[ADB] 连接设备 ${REDROID_HOST}:${REDROID_PORT}..."
MAX_CONNECT_RETRIES=5

for i in $(seq 1 $MAX_CONNECT_RETRIES); do
    # 先断开旧连接
    adb disconnect "${REDROID_HOST}:${REDROID_PORT}" 2>/dev/null || true
    sleep 1
    
    # 尝试连接
    if adb connect "${REDROID_HOST}:${REDROID_PORT}" 2>&1 | grep -q "connected"; then
        echo "[ADB] 设备连接成功"
        break
    elif adb connect "${REDROID_HOST}:${REDROID_PORT}" 2>&1 | grep -q "already connected"; then
        echo "[ADB] 设备已连接"
        break
    fi
    
    echo "[ADB] 连接失败，重试 ($i/$MAX_CONNECT_RETRIES)..."
    sleep 3
done

# 验证连接
echo "[ADB] 验证 ADB 连接..."
DEVICE_INFO=$(adb devices -l 2>&1)
echo "$DEVICE_INFO"

if echo "$DEVICE_INFO" | grep -q "${REDROID_HOST}:${REDROID_PORT}"; then
    echo "[ADB] ✓ ADB 设备连接验证成功"
else
    echo "[ADB] ✗ 警告: 设备未在列表中"
fi

# 保持 ADB Server 运行（守护进程）
echo "[ADB] ADB 初始化完成"

# 执行主命令
exec "$@"
