import { SECOND_MS, THIRTY_SECONDS_MS, WS_BASE_URL } from '@/lib/constants'
import type { AlarmWebSocketMessage, WebSocketStatus } from '@/types'
import { wsEndpoints } from './endpoints'

type MessageHandler = (message: AlarmWebSocketMessage) => void
type StatusHandler = (status: WebSocketStatus) => void

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Object.prototype.toString.call(value) === '[object Object]'
  )
}

function toCamelCaseKey(key: string): string {
  if (!key.includes('_')) return key
  return key.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())
}

function transformKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => transformKeysDeep(item))
  }
  if (!isPlainObject(value)) return value

  const out: Record<string, unknown> = {}
  for (const [key, nested] of Object.entries(value)) {
    out[toCamelCaseKey(key)] = transformKeysDeep(nested)
  }
  return out
}

class WebSocketManager {
  private ws: WebSocket | null = null
  private url: string
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectDelay = SECOND_MS
  private shouldReconnect = true
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  private messageHandlers: Set<MessageHandler> = new Set()
  private statusHandlers: Set<StatusHandler> = new Set()
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null
  private status: WebSocketStatus = 'disconnected'

  constructor(baseUrl: string = WS_BASE_URL) {
    // Convert http(s) to ws(s) if needed
    const wsUrl = baseUrl.replace(/^http/, 'ws')
    this.url = wsUrl || `ws://${window.location.host}`
  }

  private setStatus(status: WebSocketStatus): void {
    this.status = status
    this.statusHandlers.forEach((handler) => handler(status))
  }

  connect(): void {
    this.shouldReconnect = true

    const readyState = this.ws?.readyState
    if (readyState === WebSocket.OPEN || readyState === WebSocket.CONNECTING) {
      return
    }

    const wsUrl = `${this.url}${wsEndpoints.alarm}`

    this.setStatus('connecting')

    try {
      this.ws = new WebSocket(wsUrl)

      this.ws.onopen = () => {
        this.setStatus('connected')
        this.reconnectAttempts = 0
        this.startHeartbeat()
      }

      this.ws.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data) as unknown
          const message = transformKeysDeep(raw) as AlarmWebSocketMessage
          this.messageHandlers.forEach((handler) => handler(message))
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      this.ws.onerror = () => {
        this.setStatus('error')
      }

      this.ws.onclose = () => {
        this.setStatus('disconnected')
        this.stopHeartbeat()
        if (this.shouldReconnect) {
          this.scheduleReconnect()
        }
      }
    } catch (error) {
      console.error('Failed to create WebSocket:', error)
      this.setStatus('error')
      this.scheduleReconnect()
    }
  }

  disconnect(): void {
    this.shouldReconnect = false
    this.reconnectAttempts = this.maxReconnectAttempts // Prevent reconnection
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }
    this.stopHeartbeat()
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.setStatus('disconnected')
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect) return
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached')
      return
    }

    const delay = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts),
      THIRTY_SECONDS_MS // Max 30 seconds
    )

    this.reconnectAttempts++

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null
      if (this.status !== 'connected') {
        this.connect()
      }
    }, delay)
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, THIRTY_SECONDS_MS) // Every 30 seconds
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
  }

  send(message: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    } else {
      console.warn('WebSocket is not connected')
    }
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler)
    return () => this.messageHandlers.delete(handler)
  }

  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler)
    // Immediately call with current status
    handler(this.status)
    return () => this.statusHandlers.delete(handler)
  }

  getStatus(): WebSocketStatus {
    return this.status
  }

  isConnected(): boolean {
    return this.status === 'connected'
  }
}

export const wsManager = new WebSocketManager()
export default wsManager
