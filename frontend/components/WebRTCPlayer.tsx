'use client'

/**
 * Outland Frontend - WebRTC 播放器组件
 * 
 * 核心功能：
 * - WebRTC 视频流播放
 * - 屏幕触摸控制（点击、滑动）
 * - 坐标映射（考虑黑边和缩放）
 * - 生命周期管理（React StrictMode 防护）
 * 
 * 技术要点：
 * - 使用 isInitialized ref 防止 StrictMode 双重初始化
 * - DataChannel 发送前检查 readyState
 * - 精准坐标映射算法
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { Smartphone, Wifi, WifiOff, Keyboard } from 'lucide-react'
import { sendWebRTCOffer } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface WebRTCPlayerProps {
  containerId: string
  onTextInput?: () => void
}

interface ControlAction {
  action: 'click' | 'swipe' | 'input' | 'keyevent'
  x?: number
  y?: number
  x1?: number
  y1?: number
  x2?: number
  y2?: number
  duration?: number
  text?: string
  keycode?: number
}

// ============================================================================
// Constants
// ============================================================================

// 本地部署不需要 STUN 服务器
const ANDROID_WIDTH = 720
const ANDROID_HEIGHT = 1280

// ============================================================================
// WebRTCPlayer Component
// ============================================================================

export default function WebRTCPlayer({ containerId, onTextInput }: WebRTCPlayerProps) {
  // Refs
  const videoRef = useRef<HTMLVideoElement>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)
  const isInitializedRef = useRef(false)

  // State
  const [isConnected, setIsConnected] = useState(false)
  const [connectionState, setConnectionState] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [showTextModal, setShowTextModal] = useState(false)
  const [textInput, setTextInput] = useState('')

  // ============================================================================
  // Coordinate Mapping Function
  // ============================================================================

  /**
   * 将浏览器坐标转换为安卓原生坐标
   * 
   * 算法说明：
   * 1. 获取视频在浏览器中的显示尺寸 (getBoundingClientRect)
   * 2. 获取视频原始分辨率 (videoWidth/videoHeight)
   * 3. 计算 object-fit: contain 产生的黑边偏移
   * 4. 应用缩放比例得到安卓坐标
   */
  const clientToAndroid = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } => {
      const video = videoRef.current
      if (!video) return { x: 0, y: 0 }

      const rect = video.getBoundingClientRect()
      const videoWidth = video.videoWidth || ANDROID_WIDTH
      const videoHeight = video.videoHeight || ANDROID_HEIGHT

      // 计算视频在容器中的实际显示尺寸（考虑 object-fit: contain）
      const containerWidth = rect.width
      const containerHeight = rect.height

      // 计算缩放比例（取较小的值以保持宽高比）
      const scaleX = videoWidth / containerWidth
      const scaleY = videoHeight / containerHeight

      // 计算黑边偏移（居中时）
      const displayWidth = containerWidth
      const displayHeight = containerHeight
      const scaledWidth = videoWidth / scaleX
      const scaledHeight = videoHeight / scaleY
      const offsetX = (displayWidth - scaledWidth) / 2
      const offsetY = (displayHeight - scaledHeight) / 2

      // 转换坐标
      const androidX = Math.round((clientX - rect.left - offsetX) * scaleX)
      const androidY = Math.round((clientY - rect.top - offsetY) * scaleY)

      // 边界检查
      return {
        x: Math.max(0, Math.min(androidX, ANDROID_WIDTH)),
        y: Math.max(0, Math.min(androidY, ANDROID_HEIGHT)),
      }
    },
    []
  )

  // ============================================================================
  // Send Control Action via DataChannel
  // ============================================================================

  const sendControlAction = useCallback((action: ControlAction) => {
    const dataChannel = dataChannelRef.current

    // 安全检查：确保 DataChannel 处于 open 状态
    if (!dataChannel || dataChannel.readyState !== 'open') {
      console.warn('[WebRTCPlayer] DataChannel 未就绪，无法发送控制指令')
      return
    }

    try {
      dataChannel.send(JSON.stringify(action))
      console.debug('[WebRTCPlayer] 发送控制指令:', action)
    } catch (err) {
      console.error('[WebRTCPlayer] 发送控制指令失败:', err)
    }
  }, [])

  // ============================================================================
  // WebRTC Initialization
  // ============================================================================

  useEffect(() => {
    // React StrictMode 防护：防止初始化逻辑重复执行
    if (isInitializedRef.current) {
      return
    }
    isInitializedRef.current = true

    let mounted = true

    const initializeWebRTC = async () => {
      try {
        console.log('[WebRTCPlayer] 初始化 WebRTC 连接，containerId:', containerId)

        // 创建 RTCPeerConnection
        // 本地部署不需要 STUN 服务器
        const pc = new RTCPeerConnection()
        pcRef.current = pc

        // 监听连接状态变化
        pc.onconnectionstatechange = () => {
          if (!mounted) return
          setConnectionState(pc.connectionState)
          console.log('[WebRTCPlayer] 连接状态:', pc.connectionState)

          if (pc.connectionState === 'connected') {
            setIsConnected(true)
            setError(null)
          } else if (
            pc.connectionState === 'disconnected' ||
            pc.connectionState === 'failed' ||
            pc.connectionState === 'closed'
          ) {
            setIsConnected(false)
          }
        }

        // 监听 ICE 连接状态
        pc.oniceconnectionstatechange = () => {
          console.log('[WebRTCPlayer] ICE 状态:', pc.iceConnectionState)
        }

        // 创建 DataChannel（必须在创建 Offer 之前）
        const dataChannel = pc.createDataChannel('control', {
          ordered: true, // 确保消息顺序
        })
        dataChannelRef.current = dataChannel

        dataChannel.onopen = () => {
          console.log('[WebRTCPlayer] DataChannel 已打开')
        }

        dataChannel.onclose = () => {
          console.log('[WebRTCPlayer] DataChannel 已关闭')
        }

        dataChannel.onerror = (err) => {
          console.error('[WebRTCPlayer] DataChannel 错误:', err)
        }

        // 监听视频轨道
        pc.ontrack = (event) => {
          console.log('[WebRTCPlayer] 收到视频轨道:', event.track.kind)
          const [stream] = event.streams
          if (videoRef.current && stream) {
            videoRef.current.srcObject = stream
          }
        }

        // 创建 SDP Offer
        const offer = await pc.createOffer({
          offerToReceiveAudio: false,
          offerToReceiveVideo: true,
        })
        await pc.setLocalDescription(offer)

        console.log('[WebRTCPlayer] SDP Offer 已创建，正在等待服务器响应...')

        // 发送到后端获取 Answer
        const answer = await sendWebRTCOffer({
          container_id: containerId,
          sdp: offer.sdp || '',
          type: offer.type,
        })

        if (!mounted) return

        // 安全检查：确保 answer 有效
        if (!answer?.sdp) {
          throw new Error('服务器返回的 SDP Answer 无效')
        }

        // 设置远端描述
        await pc.setRemoteDescription({
          sdp: answer.sdp,
          type: answer.type as RTCSdpType,
        })

        console.log('[WebRTCPlayer] WebRTC 握手完成')
      } catch (err) {
        if (!mounted) return
        console.error('[WebRTCPlayer] WebRTC 初始化失败:', err)
        setError(err instanceof Error ? err.message : '连接失败')
        setIsConnected(false)
      }
    }

    initializeWebRTC()

    // 清理函数
    return () => {
      mounted = false

      // 关闭 DataChannel
      if (dataChannelRef.current) {
        dataChannelRef.current.close()
        dataChannelRef.current = null
      }

      // 关闭 RTCPeerConnection
      if (pcRef.current) {
        pcRef.current.close()
        pcRef.current = null
      }

      isInitializedRef.current = false
      setIsConnected(false)
      console.log('[WebRTCPlayer] WebRTC 连接已清理')
    }
  }, [containerId])

  // ============================================================================
  // Pointer Event Handlers
  // ============================================================================

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLVideoElement>) => {
      e.preventDefault()
      const { x, y } = clientToAndroid(e.clientX, e.clientY)
      sendControlAction({ action: 'click', x, y })
    },
    [clientToAndroid, sendControlAction]
  )

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLVideoElement>) => {
      // 如果需要拖拽支持，可以在这里实现
      // 目前主要用于调试
    },
    []
  )

  // ============================================================================
  // Text Input Handler
  // ============================================================================

  const handleSendText = useCallback(() => {
    if (textInput.trim()) {
      sendControlAction({ action: 'input', text: textInput })
      setTextInput('')
      setShowTextModal(false)
    }
  }, [textInput, sendControlAction])

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="relative w-full h-full bg-black flex items-center justify-center">
      {/* 视频元素 */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="max-w-full max-h-full video-container no-select"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        style={{ touchAction: 'none' }}
      />

      {/* 加载占位图 */}
      {!isConnected && !error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950 z-10">
          <div className="relative">
            <Smartphone className="w-24 h-24 text-gray-600 animate-pulse" />
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-2 h-2 bg-blue-500 rounded-full animate-ping" />
            </div>
          </div>
          <p className="mt-6 text-gray-400 text-sm font-medium">
            正在建立安全隧道...
          </p>
          <p className="mt-2 text-gray-600 text-xs">
            {connectionState || '初始化中'}
          </p>
        </div>
      )}

      {/* 错误状态 */}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950 z-10">
          <WifiOff className="w-16 h-16 text-red-500 mb-4" />
          <p className="text-red-400 font-medium">连接失败</p>
          <p className="text-gray-500 text-sm mt-2 max-w-xs text-center">
            {error}
          </p>
        </div>
      )}

      {/* 连接成功指示器 */}
      {isConnected && (
        <div className="absolute top-4 right-4 flex items-center gap-2 z-20">
          <Wifi className="w-4 h-4 text-green-500" />
          <span className="text-xs text-green-500">已连接</span>
        </div>
      )}

      {/* 文本输入按钮 */}
      <button
        onClick={() => setShowTextModal(true)}
        className="absolute bottom-4 right-4 p-3 bg-gray-900/80 hover:bg-gray-800 rounded-full z-20 transition-colors"
        title="文本输入"
      >
        <Keyboard className="w-5 h-5 text-gray-300" />
      </button>

      {/* 文本输入 Modal */}
      {showTextModal && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
          onClick={() => setShowTextModal(false)}
        >
          <div
            className="bg-gray-900 border border-gray-700 p-6 rounded-xl w-80 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-medium text-gray-100 mb-4">
              文本输入
            </h3>
            <p className="text-sm text-gray-500 mb-4">
              输入的文本将通过 ADB 发送到安卓设备
            </p>
            <input
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleSendText()
                } else if (e.key === 'Escape') {
                  setShowTextModal(false)
                }
              }}
              placeholder="输入文本..."
              className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
              autoFocus
            />
            <div className="flex gap-3 mt-4">
              <button
                onClick={() => setShowTextModal(false)}
                className="flex-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSendText}
                disabled={!textInput.trim()}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg transition-colors"
              >
                发送
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
