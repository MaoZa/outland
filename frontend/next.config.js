/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      // 所有 API 都通过 Backend 代理
      // Backend 内部转发请求到对应的 Agent

      // Auth API
      {
        source: '/api/auth/login',
        destination: 'http://backend:8000/api/auth/login',
      },
      {
        source: '/api/auth/register',
        destination: 'http://backend:8000/api/auth/register',
      },

      // Users API
      {
        source: '/api/users/me',
        destination: 'http://backend:8000/api/users/me',
      },
      {
        source: '/api/users/me/quota',
        destination: 'http://backend:8000/api/users/me/quota',
      },
      {
        source: '/api/admin/users',
        destination: 'http://backend:8000/api/admin/users',
      },
      {
        source: '/api/admin/users/:id',
        destination: 'http://backend:8000/api/admin/users/:id',
      },
      {
        source: '/api/admin/users/:id/quota',
        destination: 'http://backend:8000/api/admin/users/:id/quota',
      },
      {
        source: '/api/admin/stats',
        destination: 'http://backend:8000/api/admin/stats',
      },
      {
        source: '/api/admin/containers',
        destination: 'http://backend:8000/api/admin/containers',
      },

      // 实例列表 (由 Backend 聚合所有 Agent 的实例)
      {
        source: '/api/instances',
        destination: 'http://backend:8000/api/instances',
      },

      // 容器管理 API (通过 Backend 转发到指定 Agent)
      {
        source: '/api/containers/spawn',
        destination: 'http://backend:8000/api/containers/spawn',
      },
      {
        source: '/api/containers/:id',
        destination: 'http://backend:8000/api/containers/:id',
      },
      {
        source: '/api/containers/:id/resize',
        destination: 'http://backend:8000/api/containers/:id/resize',
      },

      // WebRTC 流媒体 (通过 Backend 转发)
      {
        source: '/api/stream/webrtc/offer',
        destination: 'http://backend:8000/api/stream/webrtc/offer',
      },

      // 画质切换 (通过 Backend 转发到 Agent)
      {
        source: '/api/stream/quality',
        destination: 'http://backend:8000/api/stream/quality',
      },

      // 连接统计 (通过 Backend 转发到 Agent)
      {
        source: '/api/stream/stats/:container_id',
        destination: 'http://backend:8000/api/stream/stats/:container_id',
      },

      // ADB 控制操作 (通过 Backend 转发)
      {
        source: '/api/action/click',
        destination: 'http://backend:8000/api/action/click',
      },
      {
        source: '/api/action/swipe',
        destination: 'http://backend:8000/api/action/swipe',
      },
      {
        source: '/api/action/text',
        destination: 'http://backend:8000/api/action/text',
      },
      {
        source: '/api/action/keyevent',
        destination: 'http://backend:8000/api/action/keyevent',
      },

      // Agent 管理 API
      {
        source: '/api/agents/:path*',
        destination: 'http://backend:8000/api/agents/:path*',
      },

      // APK 安装 API (通过 Backend 转发到 Agent)
      {
        source: '/api/apk/install',
        destination: 'http://backend:8000/api/apk/install',
      },

      // 容器 ADB 端口查询
      {
        source: '/api/container/:id/adb_port',
        destination: 'http://backend:8000/api/container/:id/adb_port',
      },

      // 健康检查
      {
        source: '/health',
        destination: 'http://backend:8000/health',
      },
    ]
  },
}

module.exports = nextConfig
