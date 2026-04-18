# Outland Backend Dockerfile
# 基于 Python 3.11 镜像，支持 ADB 和 scrcpy

FROM python:3.11-slim-bookworm

# 配置国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 配置 apt 国内镜像源（使用清华源）及所需组件
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true && \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true && \
    sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# 安装系统依赖（不再安装 Debian 的古老 scrcpy 1.17）
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    adb \
    ffmpeg \
    libsdl2-2.0-0 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && wget -q https://dl.google.com/android/repository/platform-tools-latest-linux.zip \
    && unzip -q platform-tools-latest-linux.zip \
    && cp platform-tools/adb /usr/bin/adb \
    && chmod +x /usr/bin/adb \
    && ln -sf /usr/bin/adb /usr/local/bin/adb \
    && rm -rf platform-tools platform-tools-latest-linux.zip

# scrcpy 需要的运行时目录
ENV XDG_RUNTIME_DIR=/tmp

# 安装 scrcpy v3.3.4（支持 --no-playback --no-window 无头模式）
RUN wget -q https://github.com/Genymobile/scrcpy/releases/download/v3.3.4/scrcpy-linux-x86_64-v3.3.4.tar.gz \
    && tar xzf scrcpy-linux-x86_64-v3.3.4.tar.gz \
    && cp scrcpy-linux-x86_64-v3.3.4/scrcpy /usr/local/bin/ \
    && mkdir -p /usr/local/share/scrcpy \
    && cp scrcpy-linux-x86_64-v3.3.4/scrcpy-server /usr/local/share/scrcpy/ \
    && ln -sf /usr/local/share/scrcpy/scrcpy-server /usr/local/bin/scrcpy-server \
    && rm -rf scrcpy-linux-x86_64-v3.3.4 scrcpy-linux-x86_64-v3.3.4.tar.gz



# 设置工作目录
WORKDIR /app

# 复制应用代码（包括 requirements.txt）
COPY . backend/

# 安装 Python 依赖
RUN pip install --no-cache-dir -r backend/requirements.txt

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
