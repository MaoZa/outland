#!/bin/bash
# ============================================
# Outland - Ubuntu 服务器 Redroid 一键部署脚本
# ============================================
# 使用方法: chmod +x setup-redroid.sh && sudo ./setup-redroid.sh

set -e

echo "=========================================="
echo "  Outland Redroid 部署脚本"
echo "=========================================="

# 1. 检查是否为 root
if [ "$EUID" -ne 0 ]; then
  echo "❌ 请使用 sudo 运行此脚本"
  exit 1
fi

# 2. 安装 Docker（如果尚未安装）
if ! command -v docker &> /dev/null; then
  echo "📦 正在安装 Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
  echo "✅ Docker 安装完成"
else
  echo "✅ Docker 已安装: $(docker --version)"
fi

# 3. 加载 binder 内核模块（Redroid 必需）
echo "🔧 正在加载 binder 内核模块..."
if ! lsmod | grep -q binder_linux; then
  # 尝试直接加载
  modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null || {
    echo "⚠️  binder_linux 模块未找到，尝试安装 linux-modules-extra..."
    apt-get update
    apt-get install -y "linux-modules-extra-$(uname -r)" || {
      echo "❌ 无法安装 binder 内核模块。"
      echo "   请手动安装: apt install linux-modules-extra-\$(uname -r)"
      echo "   然后重新运行此脚本"
      exit 1
    }
    modprobe binder_linux devices="binder,hwbinder,vndbinder"
  }
fi

# 确保开机自动加载
echo "binder_linux" > /etc/modules-load.d/binder.conf
echo "options binder_linux devices=binder,hwbinder,vndbinder" > /etc/modprobe.d/binder.conf
echo "✅ binder 模块已加载并设为开机启动"

# 4. 验证 binder 设备
if ls /dev/binder* &>/dev/null; then
  echo "✅ binder 设备就绪: $(ls /dev/binder*)"
else
  echo "⚠️  /dev/binder* 设备未出现，Redroid 可能无法正常启动"
fi

# 5. 开放防火墙端口
echo "🔥 配置防火墙..."
if command -v ufw &> /dev/null; then
  ufw allow 5037/tcp comment "ADB Server (Outland)"
  ufw allow 5555/tcp comment "ADB Direct (Outland)"
  echo "✅ 防火墙已放行 5037 和 5555 端口"
else
  echo "⚠️  未检测到 ufw，请手动确保 5037 和 5555 端口可访问"
fi

# 6. 启动 Redroid
echo "🚀 正在启动 Redroid 容器..."
docker compose -f docker-compose.redroid.yml up -d

echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "  Redroid 容器状态:"
docker ps --filter "name=outland-redroid" --format "  📱 {{.Names}}: {{.Status}}"
docker ps --filter "name=outland-adb-proxy" --format "  🔌 {{.Names}}: {{.Status}}"
echo ""
echo "  本机 IP 的 5037 端口 = ADB Server"
echo "  本机 IP 的 5555 端口 = ADB Direct"
echo ""
echo "  在你的 Windows 端 docker-compose.yml 中设置:"
echo "    REDROID_HOST=<本机IP>"
echo "    ADB_SERVER_SOCKET=tcp:<本机IP>:5037"
echo ""
echo "  验证连接: adb connect <本机IP>:5555"
echo "=========================================="
