/**
 * Demo-mode boot entry. Called from main.tsx before React renders when
 * VITE_DEMO_MODE=true. Starts the MSW browser worker and stubs the global
 * WebSocket so the app's wsManager can "connect" to a fake endpoint without
 * a real backend.
 *
 * See ADR-0089 for the design.
 */

import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'

let started = false

export async function initDemoMode(): Promise<void> {
  if (started) return
  started = true

  stubWebSocket()

  const worker = setupWorker(...handlers)
  await worker.start({
    onUnhandledRequest: 'bypass',
    serviceWorker: {
      url: `${import.meta.env.BASE_URL}mockServiceWorker.js`,
    },
  })


  console.info('%c[demo-mode] MSW worker started, WebSocket stubbed', 'color:#f59e0b;font-weight:bold')
}

/**
 * Replace the global WebSocket constructor with a no-op stub so the app's
 * wsManager (frontend/src/services/websocket.ts) can `new WebSocket(url)`
 * without throwing. The stub never receives messages — fine for MVP, since
 * REST polling still feeds the React Query cache. A scripted timeline that
 * pushes deltas through this stub is a planned follow-up per ADR-0089 §5.
 */
function stubWebSocket(): void {
  const RealWebSocket = window.WebSocket
  class StubSocket extends EventTarget {
    static readonly CONNECTING = 0
    static readonly OPEN = 1
    static readonly CLOSING = 2
    static readonly CLOSED = 3
    readyState: number = StubSocket.OPEN
    url: string
    onopen: ((ev: Event) => void) | null = null
    onmessage: ((ev: MessageEvent) => void) | null = null
    onclose: ((ev: CloseEvent) => void) | null = null
    onerror: ((ev: Event) => void) | null = null
    constructor(url: string) {
      super()
      this.url = url
      queueMicrotask(() => {
        const ev = new Event('open')
        this.onopen?.(ev)
        this.dispatchEvent(ev)
      })
    }
    send(_data: unknown): void { /* no-op */ }
    close(): void {
      this.readyState = StubSocket.CLOSED
      const ev = new CloseEvent('close')
      this.onclose?.(ev)
      this.dispatchEvent(ev)
    }
  }
  ;(window as unknown as { WebSocket: unknown }).WebSocket = StubSocket
  // Keep a reference so a debugger can restore if needed.
  ;(window as unknown as { __realWebSocket: typeof WebSocket }).__realWebSocket = RealWebSocket
}
