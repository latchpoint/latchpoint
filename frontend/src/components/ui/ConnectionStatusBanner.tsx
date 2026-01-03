import { useEffect, useState } from 'react'
import { useWebSocketStatus } from '@/hooks/useWebSocketStatus'
import { wsManager } from '@/services/websocket'
import { WifiOff, RefreshCw, CheckCircle, AlertCircle } from 'lucide-react'
import { Button } from './button'

export function ConnectionStatusBanner() {
  const { data: wsStatus } = useWebSocketStatus()
  const [isOnline, setIsOnline] = useState(navigator.onLine)
  const [isReconnecting, setIsReconnecting] = useState(false)
  const [showSuccess, setShowSuccess] = useState(false)

  // Track browser online/offline status
  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Show success briefly when reconnected
  useEffect(() => {
    if (wsStatus === 'connected' && isReconnecting) {
      queueMicrotask(() => {
        setIsReconnecting(false)
        setShowSuccess(true)
      })
      const timer = setTimeout(() => setShowSuccess(false), 2000)
      return () => clearTimeout(timer)
    }
  }, [wsStatus, isReconnecting])

  const handleReconnect = () => {
    setIsReconnecting(true)
    wsManager.connect()
  }

  // Determine what to show
  const showOffline = !isOnline
  const showDisconnected = isOnline && wsStatus === 'disconnected'
  const showConnecting = wsStatus === 'connecting' || isReconnecting
  const showError = wsStatus === 'error'

  // Don't render if everything is fine
  if (!showOffline && !showDisconnected && !showConnecting && !showError && !showSuccess) {
    return null
  }

  return (
    <div className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 lg:bottom-4">
      {/* Success message */}
      {showSuccess && (
        <div className="flex items-center gap-2 rounded-full bg-success px-4 py-2 text-white shadow-lg animate-in fade-in slide-in-from-bottom-2">
          <CheckCircle className="h-4 w-4" />
          <span className="text-sm font-medium">Connected</span>
        </div>
      )}

      {/* Offline - browser has no network */}
      {showOffline && (
        <div className="flex items-center gap-2 rounded-full bg-destructive px-4 py-2 text-destructive-foreground shadow-lg">
          <WifiOff className="h-4 w-4" />
          <span className="text-sm font-medium">No internet connection</span>
        </div>
      )}

      {/* Connecting */}
      {!showOffline && showConnecting && (
        <div className="flex items-center gap-2 rounded-full bg-warning px-4 py-2 text-white shadow-lg">
          <RefreshCw className="h-4 w-4 animate-spin" />
          <span className="text-sm font-medium">Reconnecting...</span>
        </div>
      )}

      {/* Disconnected - can try to reconnect */}
      {!showOffline && showDisconnected && !showConnecting && (
        <div className="flex items-center gap-2 rounded-full bg-destructive px-4 py-2 text-destructive-foreground shadow-lg">
          <WifiOff className="h-4 w-4" />
          <span className="text-sm font-medium">Disconnected</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-destructive-foreground hover:bg-white/20"
            onClick={handleReconnect}
          >
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* Error state */}
      {!showOffline && showError && !showConnecting && (
        <div className="flex items-center gap-2 rounded-full bg-destructive px-4 py-2 text-destructive-foreground shadow-lg">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm font-medium">Connection error</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-destructive-foreground hover:bg-white/20"
            onClick={handleReconnect}
          >
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  )
}
