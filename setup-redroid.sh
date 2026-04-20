#!/bin/bash
# ============================================
# Outland - Ubuntu Server Redroid One-Click Deployment Script
# ============================================
# Usage: chmod +x setup-redroid.sh && sudo ./setup-redroid.sh

set -e

echo "=========================================="
echo "  Outland Redroid Deployment Script"
echo "=========================================="

# 1. Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo"
  exit 1
fi

# 2. Install Docker (if not already installed)
if ! command -v docker &> /dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
  echo "Docker installation complete"
else
  echo "Docker is already installed: $(docker --version)"
fi

# 3. Load binder kernel module (required for Redroid)
echo "Loading binder kernel module..."
if ! lsmod | grep -q binder_linux; then
  # Try to load directly
  modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null || {
    echo "binder_linux module not found, trying to install linux-modules-extra..."
    apt-get update
    apt-get install -y "linux-modules-extra-$(uname -r)" || {
      echo "Failed to install binder kernel module."
      echo "Please install manually: apt install linux-modules-extra-$(uname -r)"
      echo "Then run this script again"
      exit 1
    }
    modprobe binder_linux devices="binder,hwbinder,vndbinder"
  }
fi

# Ensure auto-load on boot
echo "binder_linux" > /etc/modules-load.d/binder.conf
echo "options binder_linux devices=binder,hwbinder,vndbinder" > /etc/modprobe.d/binder.conf
echo "Binder module loaded and set to auto-start"

# 4. Verify binder device
if ls /dev/binder* &>/dev/null; then
  echo "Binder device ready: $(ls /dev/binder*)"
else
  echo "Warning: /dev/binder* devices not found, Redroid may not start properly"
fi

# 5. Configure firewall
echo "Configuring firewall..."
if command -v ufw &> /dev/null; then
  ufw allow 5037/tcp comment "ADB Server (Outland)"
  ufw allow 5555/tcp comment "ADB Direct (Outland)"
  echo "Firewall configured to allow ports 5037 and 5555"
else
  echo "Warning: ufw not detected, please ensure ports 5037 and 5555 are accessible"
fi

# 6. Start Redroid
echo "Starting Redroid container..."
docker compose -f docker-compose.redroid.yml up -d

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "  Redroid container status:"
docker ps --filter "name=outland-redroid" --format "  Device: {{.Names}}: {{.Status}}"
docker ps --filter "name=outland-adb-proxy" --format "  Proxy: {{.Names}}: {{.Status}}"
echo ""
echo "  Port 5037 on this machine = ADB Server"
echo "  Port 5555 on this machine = ADB Direct"
echo ""
echo "  In your Windows docker-compose.yml, set:"
echo "    REDROID_HOST=<this machine's IP>"
echo "    ADB_SERVER_SOCKET=tcp:<this machine's IP>:5037"
echo ""
echo "  Verify connection: adb connect <this machine's IP>:5555"
echo "=========================================="
