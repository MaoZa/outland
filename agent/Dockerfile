FROM python:3.11-slim-bookworm

# 设置 pip 镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 配置 apt 国内镜像源（使用清华源）及所需组件
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true && \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true && \
    sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    adb \
    ffmpeg \
    libsdl2-2.0-0 \
    libsdl2-image-2.0-0 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 安装 scrcpy v3.3.4
RUN curl -L -o /tmp/scrcpy.tar.gz https://github.com/Genymobile/scrcpy/releases/download/v3.3.4/scrcpy-linux-x86_64-v3.3.4.tar.gz

RUN tar -xzf /tmp/scrcpy.tar.gz -C /tmp/

RUN ls -la /tmp/ && ls -la /tmp/scrcpy*/

RUN mv /tmp/scrcpy-linux-x86_64-v3.3.4/scrcpy /usr/local/bin/scrcpy && chmod +x /usr/local/bin/scrcpy
RUN mv /tmp/scrcpy-linux-x86_64-v3.3.4/scrcpy-server /usr/local/bin/scrcpy-server && chmod +x /usr/local/bin/scrcpy-server
RUN mv /tmp/scrcpy-linux-x86_64-v3.3.4/icon.png /usr/local/bin/icon.png && chmod +x /usr/local/bin/icon.png

RUN rm -rf /tmp/scrcpy.tar.gz /tmp/scrcpy-linux-x86_64-v3.3.4

# 安装 Android Platform Tools
RUN wget -q https://dl.google.com/android/repository/platform-tools-latest-linux.zip

RUN unzip -q platform-tools-latest-linux.zip

RUN cp platform-tools/adb /usr/bin/adb && chmod +x /usr/bin/adb && ln -sf /usr/bin/adb /usr/local/bin/adb

RUN rm -rf platform-tools platform-tools-latest-linux.zip

# 设置 XDG 目录
ENV XDG_RUNTIME_DIR=/tmp

# 设置 SDL 视频驱动为 dummy（无头模式，避免 scrcpy 需要图形界面）
ENV SDL_VIDEODRIVER=dummy

# ADB Server 配置（与 redroid 连接）
ENV ADB_SERVER_HOST=127.0.0.1
ENV ADB_SERVER_PORT=5037
ENV REDROID_HOST=127.0.0.1
ENV REDROID_ADB_PORT=5555

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt numpy

# 复制应用代码
COPY . .

# 复制 ADB 启动脚本
COPY start_adb.sh /start_adb.sh
RUN chmod +x /start_adb.sh

# 暴露端口
EXPOSE 9090

# 启动命令：先运行 ADB 初始化脚本，再启动 uvicorn
CMD ["/start_adb.sh", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9090"]
