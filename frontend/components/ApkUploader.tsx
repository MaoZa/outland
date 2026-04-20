'use client'

/**
 * Outland Frontend - APK 上传组件
 * 
 * 提供 APK 文件上传和安装功能。
 */

import { useState, useRef } from 'react'
import { Upload, X, Package, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { installApk } from '@/lib/api'

interface ApkUploaderProps {
  containerId: string
  agentId?: string
  onClose?: () => void
}

type UploadStatus = 'idle' | 'uploading' | 'success' | 'error'

export default function ApkUploader({ containerId, agentId, onClose }: ApkUploaderProps) {
  const [status, setStatus] = useState<UploadStatus>('idle')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [successMessage, setSuccessMessage] = useState<string>('')
  const [progress, setProgress] = useState<number>(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    // 验证文件类型（支持 APK 和 XAPK）
    const fileName = file.name.toLowerCase()
    if (!fileName.endsWith('.apk') && !fileName.endsWith('.xapk')) {
      setErrorMessage('请选择 APK 或 XAPK 文件')
      setStatus('error')
      return
    }

    setSelectedFile(file)
    setStatus('idle')
    setErrorMessage('')
    setSuccessMessage('')
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    const file = event.dataTransfer.files?.[0]
    if (!file) return

    // 验证文件类型（支持 APK 和 XAPK）
    const fileName = file.name.toLowerCase()
    if (!fileName.endsWith('.apk') && !fileName.endsWith('.xapk')) {
      setErrorMessage('请选择 APK 或 XAPK 文件')
      setStatus('error')
      return
    }

    setSelectedFile(file)
    setStatus('idle')
    setErrorMessage('')
    setSuccessMessage('')
  }

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault()
  }

  const handleInstall = async () => {
    if (!selectedFile) {
      setErrorMessage('请先选择 APK 文件')
      setStatus('error')
      return
    }

    setStatus('uploading')
    setErrorMessage('')
    setSuccessMessage('')
    setProgress(0)

    // 模拟进度
    const progressInterval = setInterval(() => {
      setProgress(prev => Math.min(prev + 10, 90))
    }, 500)

    try {
      const result = await installApk(containerId, selectedFile, agentId)
      clearInterval(progressInterval)
      setProgress(100)
      
      if (result.success) {
        setStatus('success')
        setSuccessMessage(result.message || 'APK 安装成功')
      } else {
        setStatus('error')
        setErrorMessage(result.message || 'APK 安装失败')
      }
    } catch (error) {
      clearInterval(progressInterval)
      setStatus('error')
      setErrorMessage(error instanceof Error ? error.message : '安装失败')
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md bg-gray-900 rounded-xl shadow-2xl border border-gray-800">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-accent/10 rounded-lg">
              <Package className="w-5 h-5 text-accent" />
            </div>
            <h2 className="text-lg font-semibold text-white">安装 APK</h2>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 hover:bg-gray-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5 text-gray-400" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* 拖放区域 */}
          <div
            className={`
              relative border-2 border-dashed rounded-xl p-8 text-center transition-colors
              ${selectedFile ? 'border-accent bg-accent/5' : 'border-gray-700 hover:border-gray-600'}
              ${status === 'error' ? 'border-red-500 bg-red-500/5' : ''}
              ${status === 'success' ? 'border-green-500 bg-green-500/5' : ''}
            `}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".apk,.xapk"
              className="hidden"
              onChange={handleFileSelect}
            />
            
            {selectedFile ? (
              <div className="space-y-2">
                <CheckCircle className="w-12 h-12 text-accent mx-auto" />
                <p className="text-white font-medium">{selectedFile.name}</p>
                <p className="text-gray-400 text-sm">{formatFileSize(selectedFile.size)}</p>
              </div>
            ) : (
              <div className="space-y-2">
                <Upload className="w-12 h-12 text-gray-500 mx-auto" />
                <p className="text-gray-400">拖放 APK/XAPK 文件到此处</p>
                <p className="text-gray-500 text-sm">或点击选择文件</p>
              </div>
            )}
          </div>

          {/* 错误消息 */}
          {status === 'error' && errorMessage && (
            <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-400">{errorMessage}</p>
            </div>
          )}

          {/* 成功消息 */}
          {status === 'success' && successMessage && (
            <div className="flex items-start gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-green-400">{successMessage}</p>
            </div>
          )}

          {/* 进度条 */}
          {status === 'uploading' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 text-accent animate-spin" />
                <span className="text-sm text-gray-400">正在安装 APK...</span>
              </div>
              <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* 按钮 */}
          <div className="flex gap-3">
            <button
              onClick={() => {
                setSelectedFile(null)
                setStatus('idle')
                setErrorMessage('')
                setSuccessMessage('')
              }}
              disabled={status === 'uploading'}
              className="flex-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 disabled:bg-gray-800 disabled:opacity-50 text-gray-300 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleInstall}
              disabled={!selectedFile || status === 'uploading' || status === 'success'}
              className="flex-1 px-4 py-2 bg-accent hover:bg-accent/90 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {status === 'uploading' ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  安装中...
                </>
              ) : (
                <>
                  <Package className="w-4 h-4" />
                  安装 APK
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
