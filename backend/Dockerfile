# Outland Backend Dockerfile
# 基于 Python 3.11 镜像，支持 ADB 和 scrcpy

FROM python:3.11-slim-bookworm

# 配置 pip 国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 配置 apt 国内镜像源（使用清华源）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
RUN sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    adb \
    ffmpeg \
    libsdl2-2.0-0 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 下载最新 Android platform-tools
RUN wget -q https://dl.google.com/android/repository/platform-tools-latest-linux.zip

# 解压 platform-tools
RUN unzip -q platform-tools-latest-linux.zip

# 安装 adb 到系统路径
RUN cp platform-tools/adb /usr/bin/adb
RUN chmod +x /usr/bin/adb
RUN ln -sf /usr/bin/adb /usr/local/bin/adb

# 清理 platform-tools
RUN rm -rf platform-tools platform-tools-latest-linux.zip

# scrcpy 需要的运行时目录
ENV XDG_RUNTIME_DIR=/tmp

# 下载 scrcpy v3.3.4
RUN wget -q https://github.com/Genymobile/scrcpy/releases/download/v3.3.4/scrcpy-linux-x86_64-v3.3.4.tar.gz

# 解压 scrcpy
RUN tar xzf scrcpy-linux-x86_64-v3.3.4.tar.gz

# 安装 scrcpy 主程序
RUN cp scrcpy-linux-x86_64-v3.3.4/scrcpy /usr/local/bin/

# 创建 scrcpy 共享目录
RUN mkdir -p /usr/local/share/scrcpy

# 安装 scrcpy-server
RUN cp scrcpy-linux-x86_64-v3.3.4/scrcpy-server /usr/local/share/scrcpy/
RUN ln -sf /usr/local/share/scrcpy/scrcpy-server /usr/local/bin/scrcpy-server

# 清理 scrcpy 安装包
RUN rm -rf scrcpy-linux-x86_64-v3.3.4 scrcpy-linux-x86_64-v3.3.4.tar.gz

# 设置工作目录并复制应用代码
WORKDIR /app
RUN mkdir -p /app/data
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]