'use client'

/**
 * Outland Frontend - Dashboard 主页
 * 
 * 功能：
 * - 显示实例列表（容器卡片）
 * - 状态标识（运行中/已停止/已暂停）
 * - 跳转到播放器页面
 */

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  Smartphone,
  Play,
  Circle,
  RefreshCw,
  Server,
  Monitor,
} from 'lucide-react'
import { getInstances, ContainerInfo } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface InstanceWithPort extends ContainerInfo {
  adbPort?: number
}

// ============================================================================
// Status Badge Component
// ============================================================================

function StatusBadge({ status }: { status: string }) {
  const getStatusConfig = (status: string) => {
    const lower = status.toLowerCase()
    if (lower === 'running') {
      return {
        color: 'bg-green-500',
        text: '运行中',
        dotColor: 'bg-green-400',
      }
    } else if (lower === 'paused') {
      return {
        color: 'bg-yellow-500',
        text: '已暂停',
        dotColor: 'bg-yellow-400',
      }
    } else if (lower === 'exited' || lower === 'stopped') {
      return {
        color: 'bg-red-500',
        text: '已停止',
        dotColor: 'bg-red-400',
      }
    } else {
      return {
        color: 'bg-gray-500',
        text: status,
        dotColor: 'bg-gray-400',
      }
    }
  }

  const config = getStatusConfig(status)

  return (
    <div className="flex items-center gap-2">
      <span className={`w-2 h-2 rounded-full ${config.dotColor} animate-pulse`} />
      <span className="text-sm text-gray-400">{config.text}</span>
    </div>
  )
}

// ============================================================================
// Instance Card Component
// ============================================================================

function InstanceCard({
  instance,
  onConnect,
}: {
  instance: InstanceWithPort
  onConnect: (id: string) => void
}) {
  const adbPort = instance.ports.find((p) => p.container_port === 5555)?.host_port

  return (
    <div className="bg-card border border-border rounded-xl p-5 hover:bg-card-hover transition-all duration-200 group">
      {/* 头部：图标 + 名称 */}
      <div className="flex items-start gap-4">
        <div className="p-3 bg-background-secondary rounded-lg group-hover:bg-accent/10 transition-colors">
          <Smartphone className="w-8 h-8 text-gray-400 group-hover:text-accent transition-colors" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-medium text-gray-100 truncate">
            {instance.name}
          </h3>
          <p className="text-xs text-gray-500 mt-1 font-mono">
            ID: {instance.id}
          </p>
        </div>
      </div>

      {/* 状态信息 */}
      <div className="mt-4 space-y-2">
        <StatusBadge status={instance.status} />

        {/* ADB 端口 */}
        {adbPort && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Server className="w-3.5 h-3.5" />
            <span>ADB: localhost:{adbPort}</span>
          </div>
        )}

        {/* 镜像信息 */}
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Monitor className="w-3.5 h-3.5" />
          <span className="truncate">{instance.image}</span>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="mt-5">
        <button
          onClick={() => onConnect(instance.id)}
          disabled={instance.status.toLowerCase() !== 'running'}
          className={`
            w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg font-medium
            transition-all duration-200
            ${
              instance.status.toLowerCase() === 'running'
                ? 'bg-accent hover:bg-accent-hover text-white shadow-lg shadow-accent/25'
                : 'bg-gray-700 text-gray-500 cursor-not-allowed'
            }
          `}
        >
          <Play className="w-4 h-4" />
          {instance.status.toLowerCase() === 'running' ? '连接' : '离线'}
        </button>
      </div>
    </div>
  )
}

// ============================================================================
// Dashboard Page
// ============================================================================

export default function Dashboard() {
  const router = useRouter()
  const [instances, setInstances] = useState<InstanceWithPort[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchInstances = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const data = await getInstances()
      setInstances(data.instances)
    } catch (err) {
      console.error('获取实例列表失败:', err)
      setError(err instanceof Error ? err.message : '获取实例列表失败')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchInstances()
  }, [fetchInstances])

  const handleConnect = (id: string) => {
    router.push(`/player/${id}`)
  }

  return (
    <div className="min-h-screen bg-background">
      {/* 头部 */}
      <header className="border-b border-border bg-background-secondary/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-accent/10 rounded-lg">
                <Smartphone className="w-6 h-6 text-accent" />
              </div>
              <div>
                <h1 className="text-xl font-semibold text-gray-100">Outland</h1>
                <p className="text-xs text-gray-500">安卓云容器管理平台</p>
              </div>
            </div>

            {/* 刷新按钮 */}
            <button
              onClick={fetchInstances}
              disabled={isLoading}
              className="p-2 hover:bg-gray-800 rounded-lg transition-colors disabled:opacity-50"
              title="刷新"
            >
              <RefreshCw
                className={`w-5 h-5 text-gray-400 ${
                  isLoading ? 'animate-spin' : ''
                }`}
              />
            </button>
          </div>
        </div>
      </header>

      {/* 主内容 */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* 统计信息 */}
        <div className="mb-8">
          <h2 className="text-2xl font-semibold text-gray-100">实例列表</h2>
          <p className="text-sm text-gray-500 mt-1">
            共 {instances.length} 个容器
          </p>
        </div>

        {/* 错误状态 */}
        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-xl">
            <p className="text-red-400 text-sm">{error}</p>
            <button
              onClick={fetchInstances}
              className="mt-2 text-sm text-red-400 hover:text-red-300 underline"
            >
              重试
            </button>
          </div>
        )}

        {/* 加载状态 */}
        {isLoading && !instances.length && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-card border border-border rounded-xl p-5 animate-pulse"
              >
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 bg-gray-800 rounded-lg" />
                  <div className="flex-1">
                    <div className="h-5 bg-gray-800 rounded w-2/3 mb-2" />
                    <div className="h-3 bg-gray-800 rounded w-1/2" />
                  </div>
                </div>
                <div className="mt-4 space-y-2">
                  <div className="h-4 bg-gray-800 rounded w-full" />
                  <div className="h-4 bg-gray-800 rounded w-3/4" />
                </div>
                <div className="mt-5 h-10 bg-gray-800 rounded-lg" />
              </div>
            ))}
          </div>
        )}

        {/* 空状态 */}
        {!isLoading && !error && instances.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="p-4 bg-gray-800 rounded-full mb-4">
              <Smartphone className="w-12 h-12 text-gray-600" />
            </div>
            <h3 className="text-lg font-medium text-gray-400">暂无容器</h3>
            <p className="text-sm text-gray-600 mt-2">
              请先启动一个 Redroid 容器
            </p>
          </div>
        )}

        {/* 实例列表 */}
        {!isLoading && instances.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {instances.map((instance) => (
              <InstanceCard
                key={instance.id}
                instance={instance}
                onConnect={handleConnect}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
