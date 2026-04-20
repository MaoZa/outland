import type { Metadata } from 'next'
import './globals.css'
import { AuthGuard } from './auth-guard'

export const metadata: Metadata = {
  title: 'Outland - 安卓云容器平台',
  description: '自托管的安卓云容器平台，支持云游戏串流和脚本自动化',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className="bg-background text-gray-100 min-h-screen antialiased">
        <AuthGuard>{children}</AuthGuard>
      </body>
    </html>
  )
}
