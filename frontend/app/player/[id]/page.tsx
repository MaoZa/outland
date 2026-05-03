'use client'

/**
 * Outland Frontend - 播放器页面
 * 
 * 功能：
 * - 全屏沉浸式视频播放
 * - WebRTC 连接控制
 * - APK 上传安装
 * - 返回按钮
 */

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Package, Keyboard } from 'lucide-react'
import WebRTCPlayer from '@/components/WebRTCPlayer'
import ApkUploader from '@/components/ApkUploader'
import { getInstances } from '@/lib/api'

interface PageProps {
  params: { id: string }
}

export default function PlayerPage({ params }: PageProps) {
  const { id } = params
  const router = useRouter()
  const [instanceName, setInstanceName] = useState<string>('')
  const [isLoading, setIsLoading] = useState(true)
  const [showApkUploader, setShowApkUploader] = useState(false)
  const [isExternal, setIsExternal] = useState(false)

  useEffect(() => {
    let mounted = true
    
    const fetchInstanceName = async () => {
      try {
        const data = await getInstances()
        if (!mounted) return
        const instance = data.instances.find((i) => i.id === id)
        if (instance) {
          setInstanceName(instance.name)
          setIsExternal(instance.source === 'external')
        }
      } catch (err) {
        console.error('获取实例信息失败:', err)
      } finally {
        if (mounted) {
          setIsLoading(false)
        }
      }
    }

    fetchInstanceName()
    
    return () => {
      mounted = false
    }
  }, [id])

  const handleBack = () => {
    router.push('/')
  }

  return (
    <div className="fixed inset-0 bg-black flex flex-col">
      {/* 顶部导航栏 - 只保留返回按钮，减少视觉干扰 */}
      <header className="absolute top-0 left-0 z-20 p-3 pointer-events-none">
        <div className="flex items-center gap-2">
          <button
            onClick={handleBack}
            className="p-2 bg-black/40 hover:bg-black/60 backdrop-blur-sm rounded-full transition-colors pointer-events-auto"
            title="返回"
          >
            <ArrowLeft className="w-5 h-5 text-white" />
          </button>
          {instanceName && (
            <div className="px-3 py-1 bg-black/40 backdrop-blur-sm rounded-full pointer-events-none">
              <span className="text-sm text-gray-300">{instanceName}</span>
              {isExternal && (
                <span className="ml-2 px-1.5 py-0.5 text-xs bg-blue-500/30 text-blue-300 rounded">远程</span>
              )}
            </div>
          )}
        </div>
      </header>

      {/* 视频播放器区域 */}
      <main className="flex-1 relative">
        <WebRTCPlayer containerId={id} />
      </main>

      {/* 底部工具栏 */}
      <footer className="absolute bottom-0 left-0 right-0 z-20 p-2">
        <div className="flex justify-between items-end">
          {/* 左侧提示 */}
          <div className="px-3 py-1 bg-black/40 backdrop-blur-sm rounded-full pointer-events-none">
            <p className="text-xs text-gray-400 text-center">
              点击屏幕控制
            </p>
          </div>

          {/* 右侧工具按钮 */}
          <div className="flex gap-2">
            {!isExternal && (
              <button
                onClick={() => setShowApkUploader(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-black/40 hover:bg-black/60 backdrop-blur-sm rounded-full transition-colors"
                title="安装 APK"
              >
                <Package className="w-3.5 h-3.5 text-accent" />
                <span className="text-xs text-white">APK</span>
              </button>
            )}
          </div>
        </div>
      </footer>

      {/* APK 上传模态框 */}
      {showApkUploader && (
        <ApkUploader
          containerId={id}
          onClose={() => setShowApkUploader(false)}
        />
      )}
    </div>
  )
}
