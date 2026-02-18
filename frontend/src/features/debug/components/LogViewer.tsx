import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

import { api } from '@/services'
import { apiEndpoints } from '@/services/endpoints'
import { wsManager } from '@/services'
import type { WebSocketStatus } from '@/types'
import { useLogBufferInit } from '../hooks/useLogBufferInit'
import { useLogStream } from '../hooks/useLogStream'
import { LogToolbar } from './LogToolbar'
import type { LogEntry } from '../types'

/**
 * xterm.js-based log viewer that displays buffered log entries from the REST API
 * and streams new entries from the WebSocket in real-time.
 *
 * All entries are stored in an in-memory array so the terminal can be re-rendered
 * when the level filter changes. xterm.js has no concept of "hiding" lines — the
 * only way to filter is to clear and rewrite.
 */
export function LogViewer() {
  const terminalRef = useRef<HTMLDivElement>(null)
  const [terminal, setTerminal] = useState<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)

  const [paused, setPaused] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [levelFilter, setLevelFilter] = useState(0)
  const [entryCount, setEntryCount] = useState(0)
  const [wsStatus, setWsStatus] = useState<WebSocketStatus>('disconnected')

  // All entries ever received (buffer fetch + WS stream), used for re-rendering on filter change
  const allEntriesRef = useRef<LogEntry[]>([])

  // Initialize xterm.js terminal
  useEffect(() => {
    if (!terminalRef.current) return

    const term = new Terminal({
      disableStdin: true,
      scrollback: 5000,
      fontSize: 12,
      fontFamily: 'ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace',
      convertEol: true,
      theme: {
        background: '#09090b',
        foreground: '#fafafa',
        cursor: '#09090b', // Hidden cursor (matches background)
        selectionBackground: '#27272a',
        black: '#09090b',
        red: '#ef4444',
        green: '#22c55e',
        yellow: '#eab308',
        blue: '#3b82f6',
        magenta: '#a855f7',
        cyan: '#06b6d4',
        white: '#fafafa',
        brightBlack: '#71717a',
        brightRed: '#f87171',
        brightGreen: '#4ade80',
        brightYellow: '#facc15',
        brightBlue: '#60a5fa',
        brightMagenta: '#c084fc',
        brightCyan: '#22d3ee',
        brightWhite: '#ffffff',
      },
    })

    const fit = new FitAddon()

    term.loadAddon(fit)

    term.open(terminalRef.current)
    fit.fit()

    fitAddonRef.current = fit
    setTerminal(term)

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      try {
        fit.fit()
      } catch {
        // Ignore fit errors during rapid resize
      }
    })
    resizeObserver.observe(terminalRef.current)

    return () => {
      resizeObserver.disconnect()
      term.dispose()
      setTerminal(null)
      fitAddonRef.current = null
    }
  }, [])

  // Track WebSocket connection status
  useEffect(() => {
    return wsManager.onStatusChange(setWsStatus)
  }, [])

  // Fetch initial buffer — populates allEntriesRef and writes to terminal
  useLogBufferInit(terminal, allEntriesRef, {
    levelFilter,
    onCountUpdate: setEntryCount,
  })

  // Stream new entries — appends to allEntriesRef and writes to terminal
  const handleNewEntry = useCallback(() => {
    setEntryCount((prev) => prev + 1)
  }, [])

  useLogStream(terminal, allEntriesRef, {
    paused,
    autoScroll,
    levelFilter,
    onNewEntry: handleNewEntry,
  })

  // Re-render terminal when level filter changes
  const prevFilterRef = useRef(levelFilter)
  useEffect(() => {
    if (!terminal || prevFilterRef.current === levelFilter) return
    prevFilterRef.current = levelFilter

    terminal.clear()
    // Reset scrollback by writing empty content after clear
    terminal.reset()

    let count = 0
    for (const entry of allEntriesRef.current) {
      if (entry.levelNo >= levelFilter) {
        terminal.writeln(entry.formatted)
        count++
      }
    }
    setEntryCount(count)

    if (autoScroll) {
      terminal.scrollToBottom()
    }
  }, [terminal, levelFilter, autoScroll])

  // Toolbar actions
  const handlePauseToggle = useCallback(() => setPaused((prev) => !prev), [])
  const handleAutoScrollToggle = useCallback(() => setAutoScroll((prev) => !prev), [])
  const handleLevelFilterChange = useCallback((level: number) => setLevelFilter(level), [])

  const handleClear = useCallback(async () => {
    terminal?.clear()
    terminal?.reset()
    allEntriesRef.current = []
    setEntryCount(0)
    try {
      await api.delete(apiEndpoints.debug.logs)
    } catch {
      // Best-effort — the terminal is already cleared visually
    }
  }, [terminal])

  return (
    <div className="flex flex-col rounded-lg border border-border bg-card overflow-hidden mt-4 h-[calc(100vh-18rem)] min-h-[300px]">
      <LogToolbar
        paused={paused}
        autoScroll={autoScroll}
        levelFilter={levelFilter}
        onPauseToggle={handlePauseToggle}
        onAutoScrollToggle={handleAutoScrollToggle}
        onLevelFilterChange={handleLevelFilterChange}
        onClear={handleClear}
      />

      {/* Terminal container — overflow-hidden keeps xterm within bounds */}
      <div ref={terminalRef} className="flex-1 min-h-0 overflow-hidden p-2" />

      {/* Status bar */}
      <div className="flex items-center gap-4 px-3 py-1.5 border-t border-border text-xs text-muted-foreground bg-card shrink-0">
        <span>{entryCount} entries</span>
        <span>
          Streaming:{' '}
          <span className={wsStatus === 'connected' ? 'text-green-500' : 'text-yellow-500'}>
            {paused ? 'paused' : wsStatus === 'connected' ? 'active' : wsStatus}
          </span>
        </span>
        <span>Buffer: {Math.min(100, Math.round((entryCount / 500) * 100))}%</span>
      </div>
    </div>
  )
}
