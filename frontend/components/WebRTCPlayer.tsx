'use client'

/**
 * Outland Frontend - WebRTC 播放器组件
 * 
 * 核心功能：
 * - WebRTC 视频流播放
 * - 屏幕触摸控制（点击、滑动、长按）
 * - 坐标映射（考虑黑边和缩放）
 * - 生命周期管理（React StrictMode 防护）
 * 
 * 技术要点：
 * - 使用 isInitialized ref 防止 StrictMode 双重初始化
 * - DataChannel 发送前检查 readyState
 * - 精准坐标映射算法
 * - 滑动和长按检测逻辑
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { Smartphone, Wifi, WifiOff, Keyboard, Settings, ChevronDown } from 'lucide-react'
import { sendWebRTCOffer, changeQuality, QualityLevel } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface WebRTCPlayerProps {
  containerId: string
  onTextInput?: () => void
}

interface ControlAction {
  action: 'click' | 'swipe' | 'input' | 'keyevent' | 'long_press'
  x?: number
  y?: number
  x1?: number
  y1?: number
  x2?: number
  y2?: number
  duration?: number
  text?: string
  keycode?: number
  video_width?: number
  video_height?: number
}

// ============================================================================
// Constants
// ============================================================================

// 本地部署不需要 STUN 服务器
const ANDROID_WIDTH = 720
const ANDROID_HEIGHT = 1280

// 滑动检测阈值（像素）
const SWIPE_THRESHOLD = 10
// 长按检测时间（毫秒）
const LONG_PRESS_DELAY = 500

// ============================================================================
// Pointer Event State Interface
// ============================================================================

interface PointerState {
  startX: number
  startY: number
  startTime: number
  longPressTimer: ReturnType<typeof setTimeout> | null
  isMoved: boolean
}

// ============================================================================
// WebRTCPlayer Component
// ============================================================================

export default function WebRTCPlayer({ containerId }: WebRTCPlayerProps) {
  // Refs
  const videoRef = useRef<HTMLVideoElement>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)
  const isInitializedRef = useRef(false)
  const pointerStateRef = useRef<PointerState>({
    startX: 0,
    startY: 0,
    startTime: 0,
    longPressTimer: null,
    isMoved: false,
  })

  // State
  const [isConnected, setIsConnected] = useState(false)
  const [connectionState, setConnectionState] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [showTextModal, setShowTextModal] = useState(false)
  const [textInput, setTextInput] = useState('')
  // 视频分辨率（从后端获取）
  const [videoWidth, setVideoWidth] = useState(ANDROID_WIDTH)
  const [videoHeight, setVideoHeight] = useState(ANDROID_HEIGHT)

  // 画质相关状态
  const [quality, setQuality] = useState<QualityLevel>('high')
  const [showQualityMenu, setShowQualityMenu] = useState(false)
  const [isChangingQuality, setIsChangingQuality] = useState(false)
  const [reconnectTrigger, setReconnectTrigger] = useState(0)

  // 横屏检测（当视频宽度大于高度时为横屏模式）
  const isLandscape = videoWidth > videoHeight

  // 检测是否为移动设备（手机/平板）
  const isMobileDevice = useMemo(() => {
    if (typeof window === 'undefined') return false
    const userAgent = navigator.userAgent.toLowerCase()
    const isMobileUA = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(userAgent)
    const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0
    // 只有同时满足：有移动 UA 且支持触摸，才是移动设备
    return isMobileUA && isTouchDevice
  }, [])

  // ============================================================================
  // Video Resize Handler - 实时更新分辨率以支持设备旋转
  // ============================================================================

  const handleVideoResize = useCallback(() => {
    const video = videoRef.current
    if (video && video.videoWidth > 0 && video.videoHeight > 0) {
      const newWidth = video.videoWidth
      const newHeight = video.videoHeight
      // 只在分辨率实际变化时更新，避免不必要的状态更新
      if (newWidth !== videoWidth || newHeight !== videoHeight) {
        setVideoWidth(newWidth)
        setVideoHeight(newHeight)
        console.log('[WebRTCPlayer] 视频分辨率变化: %dx%d', newWidth, newHeight)
      }
    }
  }, [videoWidth, videoHeight])

  // ============================================================================
  // Coordinate Mapping Function
  // ============================================================================

  const clientToAndroid = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } => {
      const video = videoRef.current
      if (!video) return { x: 0, y: 0 }

      const rect = video.getBoundingClientRect()
      
      // 优先使用 video 元素的实时分辨率（WebRTC 解码后的实际尺寸）
      let actualWidth = video.videoWidth
      let actualHeight = video.videoHeight
      
      // 如果 video 元素分辨率无效，尝试使用 React state
      if (!actualWidth || !actualHeight) {
        actualWidth = videoWidth || ANDROID_WIDTH
        actualHeight = videoHeight || ANDROID_HEIGHT
      }
      
      // 如果仍然无效，使用默认值
      if (!actualWidth) actualWidth = ANDROID_WIDTH
      if (!actualHeight) actualHeight = ANDROID_HEIGHT

      // 容器尺寸
      const containerWidth = rect.width
      const containerHeight = rect.height

      let androidX: number
      let androidY: number

      if (isMobileDevice && isLandscape) {
        // ========== 手机端横屏模式 ==========
        // 画面已旋转90度，触摸坐标需要做对应变换

        const rotatedVideoWidth = containerHeight
        const rotatedVideoHeight = containerWidth

        const fitScale = Math.max(rotatedVideoWidth / actualWidth, rotatedVideoHeight / actualHeight)
        const displayedWidth = actualWidth * fitScale
        const displayedHeight = actualHeight * fitScale

        const cropX = (displayedWidth - rotatedVideoWidth) / 2
        const cropY = (displayedHeight - rotatedVideoHeight) / 2

        // 旋转90度：(clientX, clientY) -> (rotatedY, rotatedVideoWidth - rotatedX)
        const rotatedX = clientY - rect.top
        const rotatedY = rotatedVideoWidth - (clientX - rect.left)

        androidX = Math.round((rotatedX + cropX) / fitScale)
        androidY = Math.round((rotatedY + cropY) / fitScale)

        console.log(`[clientToAndroid] 手机横屏: client(${clientX.toFixed(0)}, ${clientY.toFixed(0)}) rect(${rect.left.toFixed(0)}, ${rect.top.toFixed(0)}) container(${containerWidth.toFixed(0)}, ${containerHeight.toFixed(0)}) -> android(${androidX}, ${androidY}) | video(${actualWidth}x${actualHeight}) rotated(${rotatedVideoWidth.toFixed(0)}x${rotatedVideoHeight.toFixed(0)}) crop(${cropX.toFixed(0)}, ${cropY.toFixed(0)}) scale(${fitScale.toFixed(3)})`)
      } else {
        // ========== PC端或竖屏模式 ==========
        // PC端使用 contain 模式，保持画面完整
        // 竖屏手机也使用 contain 模式

        const fitScale = Math.min(containerWidth / actualWidth, containerHeight / actualHeight)

        // 计算实际显示尺寸
        const displayedWidth = actualWidth * fitScale
        const displayedHeight = actualHeight * fitScale

        // 计算黑边偏移（居中）
        const offsetX = (containerWidth - displayedWidth) / 2
        const offsetY = (containerHeight - displayedHeight) / 2

        // 转换坐标：减去黑边偏移，再除以缩放因子
        androidX = Math.round((clientX - rect.left - offsetX) / fitScale)
        androidY = Math.round((clientY - rect.top - offsetY) / fitScale)

        console.log(`[clientToAndroid] PC/竖屏: client(${clientX.toFixed(0)}, ${clientY.toFixed(0)}) rect(${rect.left.toFixed(0)}, ${rect.top.toFixed(0)}) container(${containerWidth.toFixed(0)}, ${containerHeight.toFixed(0)}) -> android(${androidX}, ${androidY}) | video(${actualWidth}x${actualHeight}) display(${displayedWidth.toFixed(0)}x${displayedHeight.toFixed(0)}) offset(${offsetX.toFixed(0)}, ${offsetY.toFixed(0)}) scale(${fitScale.toFixed(3)})`)
      }

      // 边界检查
      return {
        x: Math.max(0, Math.min(androidX, actualWidth)),
        y: Math.max(0, Math.min(androidY, actualHeight)),
      }
    },
    [videoWidth, videoHeight, isMobileDevice, isLandscape]
  )

  // ============================================================================
  // Send Control Action via DataChannel
  // ============================================================================

  const sendControlAction = useCallback((action: ControlAction) => {
    const dataChannel = dataChannelRef.current

    // 安全检查：确保 DataChannel 处于 open 状态
    if (!dataChannel) {
      console.warn('[WebRTCPlayer] DataChannel 未创建，无法发送控制指令')
      return
    }

    if (dataChannel.readyState !== 'open') {
      console.warn(`[WebRTCPlayer] DataChannel 状态异常: ${dataChannel.readyState}，无法发送控制指令`)
      return
    }

    try {
      const jsonStr = JSON.stringify(action)
      dataChannel.send(jsonStr)
    // 减少日志：控制指令发送不打印，仅在错误时输出
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
        // 配置 STUN 服务器以获取公网候选地址
        const pc = new RTCPeerConnection({
          iceServers: [
            { urls: 'stun:stun.miwifi.com:3478' },
            { urls: 'stun:stun.chat.bilibili.com:3478' }
          ]
        })
        pcRef.current = pc

        // 监听连接状态变化
        pc.onconnectionstatechange = () => {
          if (!mounted) return
          setConnectionState(pc.connectionState)
          console.log('[WebRTCPlayer] 连接状态:', pc.connectionState)

          if (pc.connectionState === 'connected') {
            if (!mounted) return
            setIsConnected(true)
            setError(null)
            // 连接成功后聚焦视频元素以接收键盘事件
            setTimeout(() => {
              if (videoRef.current && mounted) {
                videoRef.current.focus()
                console.log('[WebRTCPlayer] 已聚焦视频元素')
              }
            }, 100)
          } else if (
            pc.connectionState === 'disconnected' ||
            pc.connectionState === 'failed' ||
            pc.connectionState === 'closed'
          ) {
            if (!mounted) return
            setIsConnected(false)
          }
        }

        // 监听 ICE 连接状态
        pc.oniceconnectionstatechange = () => {
          console.log('[WebRTCPlayer] ICE 状态:', pc.iceConnectionState)
        }

        // 创建 DataChannel（必须在创建 Offer 之前）
        // 优化：使用低延迟配置
        // - ordered: false - 控制指令不需要有序，优先低延迟
        // - maxRetransmits: 0 - 不重发，丢弃旧指令只保留最新
        // 注意：aiortc 端默认使用 ordered: true，需要兼容处理
        const dataChannel = pc.createDataChannel('control', {
          ordered: false,
          maxRetransmits: 0,
        })
        dataChannelRef.current = dataChannel

        dataChannel.onopen = () => {
          console.log('[WebRTCPlayer] DataChannel 已打开，readyState:', dataChannel.readyState)
          // 请求分辨率配置
          try {
            const configMsg = JSON.stringify({ action: 'config' })
            dataChannel.send(configMsg)
            console.log('[WebRTCPlayer] 已发送配置请求:', configMsg)
          } catch (err) {
            console.error('[WebRTCPlayer] 发送配置请求失败:', err)
          }
        }

        dataChannel.onclose = () => {
          console.log('[WebRTCPlayer] DataChannel 已关闭')
        }

        dataChannel.onerror = (err) => {
          console.error('[WebRTCPlayer] DataChannel 错误:', err)
        }

        // 监听后端发送的消息（如分辨率配置）
        dataChannel.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            if (data.type === 'config') {
              // 更新视频分辨率
              setVideoWidth(data.width || ANDROID_WIDTH)
              setVideoHeight(data.height || ANDROID_HEIGHT)
              console.log('[WebRTCPlayer] 收到分辨率配置:', data.width, 'x', data.height)
            }
          } catch (e) {
            console.warn('[WebRTCPlayer] 解析 DataChannel 消息失败:', e)
          }
        }

        // 监听视频轨道
        pc.ontrack = (event) => {
          console.log('[WebRTCPlayer] 收到视频轨道:', event.track.kind)
          const [stream] = event.streams
          if (videoRef.current && stream) {
            videoRef.current.srcObject = stream
          }
        }

        // 创建假视频轨道（用于触发 Safari 在 SDP 中包含视频 m-line）
        // Safari 只会在有本地视频轨道时才会发送视频 m-line
        // 即使我们不实际发送视频，这也能确保 SDP 协商正确进行
        // 使用 canvas 而非 getUserMedia，避免触发摄像头权限弹窗
        console.log('[WebRTCPlayer] 创建假视频轨道以触发 Safari SDP 视频 m-line...')
        try {
          const canvas = document.createElement('canvas')
          canvas.width = 1
          canvas.height = 1
          const ctx = canvas.getContext('2d')
          if (ctx) {
            ctx.fillStyle = 'black'
            ctx.fillRect(0, 0, 1, 1)
            const canvasStream = canvas.captureStream(0)
            const canvasTrack = canvasStream.getVideoTracks()[0]
            canvasTrack.enabled = false
            pc.addTrack(canvasTrack)
            console.log('[WebRTCPlayer] Canvas 假视频轨道已添加')
          }
        } catch (e) {
          console.warn('[WebRTCPlayer] 无法创建 canvas 假视频轨道:', e)
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
        // answer.type 是 string，需要转换为 RTCSdpType
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

      // 取消长按定时器
      if (pointerStateRef.current.longPressTimer) {
        clearTimeout(pointerStateRef.current.longPressTimer)
        pointerStateRef.current.longPressTimer = null
      }

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

      // 注意：不要在 cleanup 中调用 setIsConnected(false)
      // React 禁止在 cleanup 函数中调用 setState，这可能导致内存泄漏警告
      // 状态会在组件卸载后自动清理
      
      console.log('[WebRTCPlayer] WebRTC 连接已清理')
    }
  }, [containerId, reconnectTrigger])

  // ============================================================================
  // Keyboard Event Handler
  // ============================================================================

  // 用于累积键盘输入
  const keyboardBufferRef = useRef<string>('')
  const keyboardTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      e.preventDefault()
      
      // 获取当前按键值
      const key = e.key
      
      // 忽略修饰键和控制键
      if (e.ctrlKey || e.altKey || e.metaKey) {
        return
      }
      
      // 处理特殊键
      if (key === 'Enter') {
        // 发送累积的文本
        if (keyboardBufferRef.current.length > 0) {
          sendControlAction({ action: 'input', text: keyboardBufferRef.current })
          console.log('[WebRTCPlayer] 键盘输入:', keyboardBufferRef.current)
          keyboardBufferRef.current = ''
        }
        return
      }
      
      if (key === 'Escape') {
        // 取消输入
        keyboardBufferRef.current = ''
        return
      }
      
      if (key === 'Backspace') {
        // 删除最后一个字符
        keyboardBufferRef.current = keyboardBufferRef.current.slice(0, -1)
        return
      }
      
      // 忽略单字符按键（功能键等）
      if (key.length === 1) {
        // 累积字符
        keyboardBufferRef.current += key
        
        // 设置定时器，一段时间后自动发送
        if (keyboardTimeoutRef.current) {
          clearTimeout(keyboardTimeoutRef.current)
        }
        keyboardTimeoutRef.current = setTimeout(() => {
          if (keyboardBufferRef.current.length > 0) {
            sendControlAction({ action: 'input', text: keyboardBufferRef.current })
            console.log('[WebRTCPlayer] 键盘输入（超时发送）:', keyboardBufferRef.current)
            keyboardBufferRef.current = ''
          }
        }, 1000) // 1秒无输入后自动发送
      }
    },
    [sendControlAction]
  )

  // ============================================================================
  // Pointer Event Handlers
  // ============================================================================

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLVideoElement>) => {
      e.preventDefault()
      const { x, y } = clientToAndroid(e.clientX, e.clientY)
      
      // 重置移动状态
      pointerStateRef.current.isMoved = false
      
      // 记录起始位置和时间
      pointerStateRef.current.startX = e.clientX
      pointerStateRef.current.startY = e.clientY
      pointerStateRef.current.startTime = Date.now()
      
      // 设置长按定时器
      pointerStateRef.current.longPressTimer = setTimeout(() => {
        if (!pointerStateRef.current.isMoved) {
          // 长按触发：发送 long_press 动作（减少日志）
          sendControlAction({
            action: 'long_press', 
            x, 
            y, 
            video_width: videoWidth, 
            video_height: videoHeight 
          })
        }
      }, LONG_PRESS_DELAY)
    },
    [clientToAndroid, sendControlAction, videoWidth, videoHeight]
  )

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLVideoElement>) => {
      // 检测是否移动超过阈值
      const dx = Math.abs(e.clientX - pointerStateRef.current.startX)
      const dy = Math.abs(e.clientY - pointerStateRef.current.startY)
      
      if (dx > SWIPE_THRESHOLD || dy > SWIPE_THRESHOLD) {
        pointerStateRef.current.isMoved = true
        
        // 如果有长按定时器，取消它（用户开始滑动）
        if (pointerStateRef.current.longPressTimer) {
          clearTimeout(pointerStateRef.current.longPressTimer)
          pointerStateRef.current.longPressTimer = null
        }
      }
    },
    []
  )

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLVideoElement>) => {
      e.preventDefault()
      
      // 取消长按定时器
      if (pointerStateRef.current.longPressTimer) {
        clearTimeout(pointerStateRef.current.longPressTimer)
        pointerStateRef.current.longPressTimer = null
      }
      
      const { x, y } = clientToAndroid(e.clientX, e.clientY)
      const startX = pointerStateRef.current.startX
      const startY = pointerStateRef.current.startY
      const startTime = pointerStateRef.current.startTime
      
      // 计算移动距离
      const dx = Math.abs(e.clientX - startX)
      const dy = Math.abs(e.clientY - startY)
      const distance = Math.sqrt(dx * dx + dy * dy)
      
      // 计算滑动持续时间（最少 50ms，避免太快）
      const duration = Math.max(50, Date.now() - startTime)
      
      if (distance > SWIPE_THRESHOLD) {
        // 滑动操作（减少日志）
        const { x: x1, y: y1 } = clientToAndroid(startX, startY)
        sendControlAction({
          action: 'swipe',
          x1,
          y1,
          x2: x,
          y2: y,
          duration,
          video_width: videoWidth,
          video_height: videoHeight,
        })
      } else if (!pointerStateRef.current.isMoved) {
        // 短按操作（没有移动且没有触发长按，减少日志）
        sendControlAction({
          action: 'click',
          x,
          y,
          video_width: videoWidth,
          video_height: videoHeight,
        })
      }
    },
    [clientToAndroid, sendControlAction, videoWidth, videoHeight]
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
  // Quality Change Handler
  // ============================================================================

  const handleQualityChange = useCallback(
    async (newQuality: QualityLevel) => {
      if (newQuality === quality || isChangingQuality) return

      setIsChangingQuality(true)
      setShowQualityMenu(false)
      setError(null)

      try {
        const result = await changeQuality(containerId, newQuality)
        console.log('[WebRTCPlayer] 画质切换成功:', result)
        setQuality(newQuality)

        // 关闭现有连接
        setIsConnected(false)
        if (pcRef.current) {
          pcRef.current.close()
          pcRef.current = null
        }

        // 重置初始化标记，触发重新连接
        isInitializedRef.current = false
        setReconnectTrigger(t => t + 1)
      } catch (err) {
        console.error('[WebRTCPlayer] 画质切换失败:', err)
        setError(err instanceof Error ? err.message : '画质切换失败')
      } finally {
        setIsChangingQuality(false)
      }
    },
    [containerId, quality, isChangingQuality]
  )

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div
      className="relative w-full h-full bg-black flex items-center justify-center p-[5%]"
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      {/* 视频元素 */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="video-container no-select"
        onResize={handleVideoResize}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{ 
          touchAction: 'none',
          // 手机端横屏时旋转90度以匹配物理设备方向
          // 所有模式：contain 模式保持画面完整，居中显示，5%内边距产生黑边
          transform: isMobileDevice && isLandscape ? 'rotate(90deg)' : 'none',
          transformOrigin: 'center center',
          objectFit: 'contain'
        }}
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

      {/* 连接成功指示器 - pointer-events-none 让触摸穿透 */}
      {isConnected && !showQualityMenu && (
        <div className="absolute top-4 right-4 flex items-center gap-2 z-20 pointer-events-none">
          <Wifi className="w-4 h-4 text-green-500" />
          <span className="text-xs text-green-500">已连接</span>
        </div>
      )}

      {/* 画质选择器 */}
      {isConnected && (
        <div className="absolute top-4 right-4 z-30">
          {isChangingQuality ? (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/20 border border-blue-500/30 rounded-lg">
              <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs text-blue-400">切换中...</span>
            </div>
          ) : (
            <div className="relative">
              <button
                onClick={() => setShowQualityMenu(!showQualityMenu)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800/80 hover:bg-gray-700/80 border border-gray-600/50 rounded-lg transition-colors pointer-events-auto"
              >
                <Settings className="w-4 h-4 text-gray-400" />
                <span className="text-xs text-gray-300 capitalize">{quality}</span>
                <ChevronDown className="w-3 h-3 text-gray-500" />
              </button>

              {/* 画质选择菜单 */}
              {showQualityMenu && (
                <div className="absolute right-0 top-full mt-1 py-1 bg-gray-900 border border-gray-700 rounded-lg shadow-xl min-w-[120px]">
                  {(['high', 'medium', 'low'] as QualityLevel[]).map((q) => (
                    <button
                      key={q}
                      onClick={() => handleQualityChange(q)}
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-800 transition-colors ${
                        q === quality
                          ? 'text-blue-400 bg-blue-500/10'
                          : 'text-gray-300'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="capitalize">{q}</span>
                        <span className="text-xs text-gray-500 ml-2">
                          {q === 'high' ? '720p' : q === 'medium' ? '480p' : '360p'}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 横屏模式指示器 - pointer-events-none 让触摸穿透 */}
      {isLandscape && isConnected && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 px-3 py-1 bg-amber-500/20 border border-amber-500/30 rounded-full pointer-events-none">
          <span className="text-xs text-amber-400">横屏模式</span>
        </div>
      )}

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
