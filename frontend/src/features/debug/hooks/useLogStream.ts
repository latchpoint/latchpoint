import { type MutableRefObject, useEffect, useRef } from 'react'
import type { Terminal } from '@xterm/xterm'

import { wsManager } from '@/services'
import type { AlarmWebSocketMessage } from '@/types'
import type { LogEntry } from '../types'

/**
 * Subscribes to WebSocket `log_entry` messages and writes them to the xterm.js
 * terminal. Respects pause state by queuing entries and flushing on unpause.
 * All entries are also appended to the shared entries ref for re-filtering.
 */
export function useLogStream(
  terminal: Terminal | null,
  allEntriesRef: MutableRefObject<LogEntry[]>,
  options: {
    paused: boolean
    autoScroll: boolean
    levelFilter: number
    onNewEntry: () => void
  }
) {
  const queueRef = useRef<LogEntry[]>([])
  const pausedRef = useRef(options.paused)
  const levelFilterRef = useRef(options.levelFilter)
  const autoScrollRef = useRef(options.autoScroll)

  // Keep refs in sync with latest prop values
  pausedRef.current = options.paused
  levelFilterRef.current = options.levelFilter
  autoScrollRef.current = options.autoScroll

  // Flush queued entries when unpausing
  useEffect(() => {
    if (!options.paused && terminal && queueRef.current.length > 0) {
      for (const entry of queueRef.current) {
        if (entry.levelNo >= levelFilterRef.current) {
          terminal.writeln(entry.formatted)
        }
      }
      queueRef.current = []
      if (autoScrollRef.current) {
        terminal.scrollToBottom()
      }
    }
  }, [options.paused, terminal])

  useEffect(() => {
    if (!terminal) return

    const unsubscribe = wsManager.onMessage((message: AlarmWebSocketMessage) => {
      if (message.type !== 'log_entry') return

      const entry = message.payload as LogEntry

      // Always store for re-filtering, regardless of pause/filter state
      allEntriesRef.current.push(entry)

      if (pausedRef.current) {
        queueRef.current.push(entry)
        return
      }

      if (entry.levelNo >= levelFilterRef.current) {
        terminal.writeln(entry.formatted)
        options.onNewEntry()
        if (autoScrollRef.current) {
          terminal.scrollToBottom()
        }
      }
    })

    return unsubscribe
  }, [terminal, allEntriesRef, options.onNewEntry])
}
