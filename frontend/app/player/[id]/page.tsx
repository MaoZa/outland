'use client'

/**
 * Outland Frontend - 播放器页面
 * 
 * 功能：
 * - 全屏沉浸式视频播放
 * - WebRTC 连接控制
 * - 返回按钮
 */

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Smartphone } from 'lucide-react'
import WebRTCPlayer from '@/components/WebRTCPlayer'
import { getInstances } from '@/lib/api'

interface PageProps {
  params: { id: string }
}

export default function PlayerPage({ params }: PageProps) {
  const { id } = params
  const router = useRouter()
  const [instanceName, setInstanceName] = useState<string>('')
  const [isLoading, setIsLoading] = useState(true)

  // 获取实例名称用于显示
  useEffect(() => {
    const fetchInstanceName = async () => {
      try {
        const data = await getInstances()
        const instance = data.instances.find((i) => i.id === id)
        if (instance) {
          setInstanceName(instance.name)
        }
      } catch (err) {
        console.error('获取实例信息失败:', err)
      } finally {
        setIsLoading(false)
      }
    }

    fetchInstanceName()
  }, [id])

  const handleBack = () => {
    router.push('/')
  }

  return (
    <div className="fixed inset-0 bg-black flex flex-col">
      {/* 顶部导航栏 */}
      <header className="absolute top-0 left-0 right-0 z-30 p-4">
        <div className="flex items-center gap-4">
          {/* 返回按钮 */}
          <button
            onClick={handleBack}
            className="p-2 bg-black/50 hover:bg-black/70 backdrop-blur-sm rounded-full transition-colors"
            title="返回"
          >
            <ArrowLeft className="w-5 h-5 text-white" />
          </button>

          {/* 实例名称 */}
          {!isLoading && instanceName && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-black/50 backdrop-blur-sm rounded-full">
              <Smartphone className="w-4 h-4 text-accent" />
              <span className="text-sm text-white font-medium">
                {instanceName}
              </span>
            </div>
          )}

          {/* 加载中 */}
          {isLoading && (
            <div className="px-3 py-1.5 bg-black/50 backdrop-blur-sm rounded-full">
              <span className="text-sm text-gray-400">加载中...</span>
            </div>
          )}
        </div>
      </header>

      {/* 视频播放器区域 */}
      <main className="flex-1 relative">
        <WebRTCPlayer containerId={id} />
      </main>

      {/* 底部提示 */}
      <footer className="absolute bottom-0 left-0 right-0 z-30 p-4 pointer-events-none">
        <div className="flex justify-center">
          <div className="px-4 py-2 bg-black/50 backdrop-blur-sm rounded-full">
            <p className="text-xs text-gray-400 text-center">
              点击屏幕控制 · 使用键盘按钮输入文本
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
