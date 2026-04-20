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
  RefreshCw,
  Server,
  Monitor,
  Plus,
  Trash2,
  X,
  MonitorOff,
  Gauge,
  Cpu,
  Maximize2,
  LogOut,
} from 'lucide-react'
import { getInstances, spawnContainer, deleteContainer, getAgents, ContainerInfo, SpawnRequest, AgentInfo, resizeContainer } from '@/lib/api'
import { useAuth } from '@/lib/auth'

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
  onDelete,
  onResize,
  isDeleting,
}: {
  instance: InstanceWithPort
  onConnect: (id: string) => void
  onDelete: (id: string) => void
  onResize: (id: string) => void
  isDeleting: boolean
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
        {/* 修改分辨率按钮 */}
        <button
          onClick={() => onResize(instance.id)}
          disabled={isDeleting || instance.status.toLowerCase() !== 'running'}
          className="p-2 opacity-0 group-hover:opacity-100 hover:bg-blue-500/20 rounded-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          title="修改分辨率"
        >
          <Maximize2 className="w-4 h-4 text-blue-400" />
        </button>
        {/* 删除按钮 */}
        <button
          onClick={() => onDelete(instance.id)}
          disabled={isDeleting}
          className="p-2 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 rounded-lg transition-all duration-200 disabled:opacity-50"
          title="删除容器"
        >
          <Trash2 className="w-4 h-4 text-red-400" />
        </button>
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
// Configuration Presets
// ============================================================================

const CONFIG_PRESETS = [
  {
    id: 'low',
    name: '低配版',
    description: '省电，适合轻度使用',
    width: 720,
    height: 1280,
    fps: 30,
    icon: MonitorOff,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10 border-blue-500/30',
  },
  {
    id: 'high',
    name: '高配版',
    description: '流畅，适合游戏串流',
    width: 1080,
    height: 1920,
    fps: 60,
    icon: Gauge,
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/30',
  },
  {
    id: 'landscape_low',
    name: '横屏低配',
    description: '横屏模式，省电',
    width: 1280,
    height: 720,
    fps: 30,
    icon: Maximize2,
    color: 'text-green-400',
    bgColor: 'bg-green-500/10 border-green-500/30',
  },
  {
    id: 'landscape_high',
    name: '横屏高配',
    description: '横屏高画质',
    width: 1920,
    height: 1080,
    fps: 60,
    icon: Maximize2,
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10 border-amber-500/30',
  },
]

// ============================================================================
// Create Container Modal
// ============================================================================

function CreateContainerModal({
  isOpen,
  onClose,
  onCreate,
  isCreating,
  agents,
}: {
  isOpen: boolean
  onClose: () => void
  onCreate: (config: SpawnRequest) => void
  isCreating: boolean
  agents: AgentInfo[]
}) {
  const [selectedPreset, setSelectedPreset] = useState<string>('low')
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [showAgentSelect, setShowAgentSelect] = useState(false)

  // 自动选择第一个 Agent（如果只有一个）
  // 注意：不要在依赖中包含 selectedAgent，否则会导致无限循环
  useEffect(() => {
    let mounted = true
    if (agents.length === 1 && !selectedAgent) {
      // 使用 setTimeout 避免在渲染期间直接调用 setState
      const timer = setTimeout(() => {
        if (mounted) {
          setSelectedAgent(agents[0].agent_id)
        }
      }, 0)
      return () => {
        mounted = false
        clearTimeout(timer)
      }
    }
    return () => {
      mounted = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents.length])

  if (!isOpen) return null

  const selectedConfig = CONFIG_PRESETS.find((p) => p.id === selectedPreset)!

  const handleCreate = () => {
    if (agents.length > 1 && !selectedAgent) {
      alert('请选择一个 Agent')
      return
    }
    onCreate({
      agent_id: selectedAgent || agents[0]?.agent_id,
      width: selectedConfig.width,
      height: selectedConfig.height,
      fps: selectedConfig.fps,
    })
  }

  const selectedAgentInfo = agents.find(a => a.agent_id === selectedAgent)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-card border border-border rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-gray-100">创建容器</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 max-h-[60vh] overflow-y-auto">
          {/* Agent 选择 */}
          <div className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-gray-400">选择 Agent</p>
              <span className="text-xs text-gray-500">{agents.length} 个可用</span>
            </div>
            
            {agents.length === 0 ? (
              <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-center">
                <p className="text-red-400 text-sm">没有可用的 Agent</p>
                <p className="text-xs text-gray-500 mt-1">请确保 Agent 已启动并注册到后端</p>
              </div>
            ) : agents.length === 1 ? (
              <div className="p-3 bg-background-secondary rounded-lg flex items-center gap-3">
                <div className="p-2 bg-accent/10 rounded-lg">
                  <Cpu className="w-5 h-5 text-accent" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-200">{agents[0].agent_id}</p>
                  <p className="text-xs text-gray-500 truncate">{agents[0].url}</p>
                </div>
                <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              </div>
            ) : (
              <div className="space-y-2">
                {agents.map((agent) => (
                  <button
                    key={agent.agent_id}
                    onClick={() => setSelectedAgent(agent.agent_id)}
                    className={`
                      w-full flex items-center gap-3 p-3 rounded-lg border transition-all duration-200
                      ${selectedAgent === agent.agent_id
                        ? 'bg-accent/10 border-accent'
                        : 'bg-background-secondary border-border hover:border-gray-600'
                      }
                    `}
                  >
                    <div className={`p-2 rounded-lg ${selectedAgent === agent.agent_id ? 'bg-accent/20' : 'bg-gray-700'}`}>
                      <Cpu className={`w-5 h-5 ${selectedAgent === agent.agent_id ? 'text-accent' : 'text-gray-400'}`} />
                    </div>
                    <div className="flex-1 text-left">
                      <p className="text-sm font-medium text-gray-200">{agent.agent_id}</p>
                      <p className="text-xs text-gray-500 truncate">{agent.url}</p>
                    </div>
                    <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 分隔线 */}
          <div className="border-t border-border my-4" />

          <p className="text-sm text-gray-400 mb-4">选择容器配置</p>

          {/* Preset Cards */}
          <div className="space-y-3">
            {CONFIG_PRESETS.map((preset) => {
              const Icon = preset.icon
              const isSelected = selectedPreset === preset.id

              return (
                <button
                  key={preset.id}
                  onClick={() => setSelectedPreset(preset.id)}
                  className={`
                    w-full flex items-center gap-4 p-4 rounded-xl border transition-all duration-200
                    ${isSelected
                      ? `${preset.bgColor} border-${preset.color.split('-')[1]}-500`
                      : 'bg-background-secondary border-border hover:border-gray-600'
                    }
                  `}
                >
                  <div className={`p-2 rounded-lg ${preset.bgColor}`}>
                    <Icon className={`w-6 h-6 ${preset.color}`} />
                  </div>
                  <div className="flex-1 text-left">
                    <p className="font-medium text-gray-100">{preset.name}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {preset.description}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-mono text-gray-300">
                      {preset.width}x{preset.height}
                    </p>
                    <p className="text-xs text-gray-500">@{preset.fps}fps</p>
                  </div>
                </button>
              )
            })}
          </div>

          {/* Selected Config Summary */}
          <div className="mt-5 p-3 bg-background-secondary rounded-lg">
            <p className="text-xs text-gray-500 mb-2">配置详情</p>
            <div className="flex gap-4 text-sm">
              <div>
                <span className="text-gray-500">Agent：</span>
                <span className="text-gray-300">{selectedAgentInfo?.agent_id || agents[0]?.agent_id || '-'}</span>
              </div>
            </div>
            <div className="flex gap-4 text-sm mt-1">
              <div>
                <span className="text-gray-500">分辨率：</span>
                <span className="text-gray-300 font-mono">
                  {selectedConfig.width}x{selectedConfig.height}
                </span>
              </div>
              <div>
                <span className="text-gray-500">帧率：</span>
                <span className="text-gray-300 font-mono">{selectedConfig.fps}Hz</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 border-t border-border">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={isCreating || agents.length === 0}
            className="flex-1 px-4 py-2.5 bg-accent hover:bg-accent-hover text-white rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isCreating ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                创建中...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                创建
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Delete Confirmation Modal
// ============================================================================

function DeleteConfirmModal({
  isOpen,
  containerId,
  containerName,
  onClose,
  onConfirm,
  isDeleting,
}: {
  isOpen: boolean
  containerId: string
  containerName: string
  onClose: () => void
  onConfirm: () => void
  isDeleting: boolean
}) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-card border border-border rounded-2xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border">
          <div className="p-2 bg-red-500/10 rounded-lg">
            <Trash2 className="w-5 h-5 text-red-400" />
          </div>
          <h2 className="text-lg font-semibold text-gray-100">删除容器</h2>
        </div>

        {/* Content */}
        <div className="px-6 py-5">
          <p className="text-gray-300">
            确定要删除容器 <span className="font-medium text-gray-100">{containerName}</span> 吗？
          </p>
          <p className="text-sm text-gray-500 mt-2">
            此操作不可恢复，容器内的所有数据将被永久删除。
          </p>
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 border-t border-border">
          <button
            onClick={onClose}
            disabled={isDeleting}
            className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex-1 px-4 py-2.5 bg-red-500 hover:bg-red-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isDeleting ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                删除中...
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4" />
                删除
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Resize Container Modal
// ============================================================================

function ResizeModal({
  isOpen,
  containerName,
  onClose,
  onResize,
  isResizing,
}: {
  isOpen: boolean
  containerName: string
  onClose: () => void
  onResize: (config: SpawnRequest) => void
  isResizing: boolean
}) {
  const [selectedPreset, setSelectedPreset] = useState<string>('low')

  if (!isOpen) return null

  const selectedConfig = CONFIG_PRESETS.find((p) => p.id === selectedPreset)!

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-card border border-border rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Maximize2 className="w-5 h-5 text-blue-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-100">修改分辨率</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5">
          <p className="text-sm text-gray-400 mb-5">
            选择新的分辨率配置（容器：<span className="text-gray-300">{containerName}</span>）
          </p>

          {/* 预设选择 */}
          <div className="space-y-3">
            {CONFIG_PRESETS.map((preset) => (
              <button
                key={preset.id}
                onClick={() => setSelectedPreset(preset.id)}
                className={`
                  w-full p-4 rounded-xl border transition-all duration-200 text-left
                  ${preset.bgColor}
                  ${selectedPreset === preset.id ? 'ring-2 ring-accent' : ''}
                `}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <preset.icon className={`w-5 h-5 ${preset.color}`} />
                    <div>
                      <p className={`font-medium ${preset.color}`}>{preset.name}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{preset.description}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-gray-300">{preset.width}x{preset.height}</p>
                    <p className="text-xs text-gray-500">@{preset.fps}fps</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 border-t border-border">
          <button
            onClick={onClose}
            disabled={isResizing}
            className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={() => onResize({
              width: selectedConfig.width,
              height: selectedConfig.height,
              fps: selectedConfig.fps,
            })}
            disabled={isResizing}
            className="flex-1 px-4 py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isResizing ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                修改中...
              </>
            ) : (
              <>
                <Maximize2 className="w-4 h-4" />
                确认修改
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Dashboard Page
// ============================================================================

export default function Dashboard() {
  const router = useRouter()
  const { user, logout } = useAuth()
  const [instances, setInstances] = useState<InstanceWithPort[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Modal 状态
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [isCreateLoading, setIsCreateLoading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)
  const [isDeleteLoading, setIsDeleteLoading] = useState(false)
  const [resizeTarget, setResizeTarget] = useState<{ id: string; name: string } | null>(null)
  const [isResizeLoading, setIsResizeLoading] = useState(false)

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

  const fetchAgents = useCallback(async () => {
    try {
      const data = await getAgents()
      setAgents(data.agents)
    } catch (err) {
      console.error('获取 Agent 列表失败:', err)
      // Agent 获取失败不影响主流程
      setAgents([])
    }
  }, [])

  useEffect(() => {
    fetchInstances()
    fetchAgents()
  }, [fetchInstances, fetchAgents])

  const handleConnect = (id: string) => {
    router.push(`/player/${id}`)
  }

  // 创建容器
  const handleCreateContainer = async (config: SpawnRequest) => {
    try {
      setIsCreateLoading(true)
      await spawnContainer(config)
      setIsCreateModalOpen(false)
      // 刷新列表
      await fetchInstances()
    } catch (err) {
      console.error('创建容器失败:', err)
      alert(err instanceof Error ? err.message : '创建容器失败')
    } finally {
      setIsCreateLoading(false)
    }
  }

  // 删除容器
  const handleDeleteContainer = async () => {
    if (!deleteTarget) return

    try {
      setIsDeleteLoading(true)
      await deleteContainer(deleteTarget.id, true)
      setDeleteTarget(null)
      // 刷新列表
      await fetchInstances()
    } catch (err) {
      console.error('删除容器失败:', err)
      alert(err instanceof Error ? err.message : '删除容器失败')
    } finally {
      setIsDeleteLoading(false)
    }
  }

  // 修改分辨率
  const handleResizeContainer = async (config: SpawnRequest) => {
    if (!resizeTarget) return

    try {
      setIsResizeLoading(true)
      const resizeInstance = instances.find((i) => i.id === resizeTarget.id)
      await resizeContainer({ 
        ...config, 
        container_id: resizeTarget.id,
        agent_id: resizeInstance?.agent_id
      })
      setResizeTarget(null)
      // 刷新列表
      await fetchInstances()
    } catch (err) {
      console.error('修改分辨率失败:', err)
      alert(err instanceof Error ? err.message : '修改分辨率失败')
    } finally {
      setIsResizeLoading(false)
    }
  }

  // 获取当前删除目标实例
  const deleteTargetInstance = instances.find((i) => i.id === deleteTarget?.id)

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

            {/* 操作按钮组 */}
            <div className="flex items-center gap-2">
              {/* 用户信息 */}
              {user && (
                <span className="text-xs text-gray-500 hidden sm:inline">
                  {user.email}
                </span>
              )}

              {/* 退出按钮 */}
              <button
                onClick={logout}
                className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
                title="退出登录"
              >
                <LogOut className="w-5 h-5 text-gray-400" />
              </button>

              {/* 创建容器按钮 */}
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="flex items-center gap-2 px-3 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg transition-colors"
              >
                <Plus className="w-4 h-4" />
                <span className="text-sm font-medium">创建容器</span>
              </button>

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
              点击右上角「创建容器」开始
            </p>
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="mt-4 flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" />
              <span>创建容器</span>
            </button>
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
                onDelete={(id) => {
                  setDeleteTarget({ id, name: instance.name })
                }}
                onResize={(id) => {
                  setResizeTarget({ id, name: instance.name })
                }}
                isDeleting={isDeleteLoading && deleteTarget?.id === instance.id}
              />
            ))}
          </div>
        )}
      </main>

      {/* 创建容器 Modal */}
      <CreateContainerModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onCreate={handleCreateContainer}
        isCreating={isCreateLoading}
        agents={agents}
      />

      {/* 删除确认 Modal */}
      <DeleteConfirmModal
        isOpen={deleteTarget !== null}
        containerId={deleteTarget?.id || ''}
        containerName={deleteTargetInstance?.name || deleteTarget?.name || ''}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteContainer}
        isDeleting={isDeleteLoading}
      />

      {/* 修改分辨率 Modal */}
      <ResizeModal
        isOpen={resizeTarget !== null}
        containerName={resizeTarget?.name || ''}
        onClose={() => setResizeTarget(null)}
        onResize={handleResizeContainer}
        isResizing={isResizeLoading}
      />
    </div>
  )
}
