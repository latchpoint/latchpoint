import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import wsManager from '@/services/websocket'
import { wsEndpoints } from '@/services/endpoints'

type MockSocket = {
  url: string
  readyState: number
  send: (data: string) => void
  close: () => void
  onopen: null | (() => void)
  onmessage: null | ((ev: { data: string }) => void)
  onclose: null | (() => void)
  onerror: null | (() => void)
}

  describe('WebSocketManager', () => {
  const sockets: MockSocket[] = []

  function installMockWebSocket() {
    sockets.length = 0

    class WebSocketMock {
      static CONNECTING = 0
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3

      public url: string
      public readyState = WebSocketMock.CONNECTING
      public onopen: null | (() => void) = null
      public onmessage: null | ((ev: { data: string }) => void) = null
      public onclose: null | (() => void) = null
      public onerror: null | (() => void) = null
      public send = vi.fn()
      public close = vi.fn(() => {
        this.readyState = WebSocketMock.CLOSED
        this.onclose?.()
      })

      constructor(url: string) {
        this.url = url
        sockets.push(this as unknown as MockSocket)
      }
    }

    vi.stubGlobal('WebSocket', WebSocketMock as unknown as typeof WebSocket)
  }

  beforeEach(() => {
    installMockWebSocket()
    wsManager.disconnect()
  })

  afterEach(() => {
    wsManager.disconnect()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('connects and notifies status changes', () => {
    const statuses: string[] = []
    const unsubscribe = wsManager.onStatusChange((s) => statuses.push(s))

    wsManager.connect()

    expect(statuses.at(-1)).toBe('connecting')
    expect(sockets).toHaveLength(1)

    sockets[0].readyState = (globalThis.WebSocket as typeof WebSocket).OPEN
    sockets[0].onopen?.()

    expect(statuses.at(-1)).toBe('connected')

    unsubscribe()
  })

  it('camel-cases incoming messages', () => {
    const received: unknown[] = []
    const unsubscribe = wsManager.onMessage((m) => received.push(m))

    wsManager.connect()
    sockets[0].readyState = (globalThis.WebSocket as typeof WebSocket).OPEN
    sockets[0].onopen?.()

    sockets[0].onmessage?.({ data: JSON.stringify({ type: 'system_status', payload: { has_next: true } }) })

    expect(received).toEqual([{ type: 'system_status', payload: { hasNext: true } }])
    unsubscribe()
  })

  it('sends heartbeat pings while connected', async () => {
    vi.useFakeTimers()

    wsManager.connect()
    sockets[0].readyState = (globalThis.WebSocket as typeof WebSocket).OPEN
    sockets[0].onopen?.()

    await vi.advanceTimersByTimeAsync(30_000)

    expect(sockets[0].send).toHaveBeenCalledWith(JSON.stringify({ type: 'ping' }))
  })

  it('reconnects after a close when enabled', async () => {
    vi.useFakeTimers()

    wsManager.connect()
    sockets[0].readyState = (globalThis.WebSocket as typeof WebSocket).OPEN
    sockets[0].onopen?.()

    sockets[0].close()
    expect(wsManager.getStatus()).toBe('disconnected')

    await vi.advanceTimersByTimeAsync(1_000)

    expect(sockets).toHaveLength(2)
    expect(sockets[1].url).toContain(wsEndpoints.alarm)
  })
})
