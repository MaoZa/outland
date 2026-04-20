# Outland Frontend Dockerfile
# 基于 Node.js 20 (多阶段构建)

FROM node:20-bullseye-slim AS builder

# 配置 npm 国内镜像源（使用阿里云）
RUN npm config set registry https://registry.npmmirror.com
RUN npm config set fetch-timeout 120000
RUN npm config set fetch-retries 3
RUN npm config set fetch-retry-mintimeout 20000
RUN npm config set fetch-retry-maxtimeout 60000

# 配置 apt 国内镜像源（使用阿里云）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
RUN sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true

# 安装构建依赖
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制 package 文件
COPY package*.json ./

# 安装依赖（添加重试逻辑）
RUN npm ci --prefer-offline || npm ci

# 复制源代码
COPY . .

# 构建应用
RUN npm run build

# 生产环境镜像
FROM node:20-bullseye-slim

# 配置 npm 国内镜像源
RUN npm config set registry https://registry.npmmirror.com

WORKDIR /app

# 复制构建产物
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/next.config.js ./
COPY --from=builder /app/tsconfig.json ./

# 安装生产依赖
RUN npm ci --only=production
RUN npm cache clean --force

# 暴露端口
EXPOSE 3000

# 启动命令
CMD ["npm", "start"]