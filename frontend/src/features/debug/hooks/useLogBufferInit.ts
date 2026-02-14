import { type MutableRefObject, useEffect, useRef } from 'react'
import type { Terminal } from '@xterm/xterm'

import { api } from '@/services'
import { apiEndpoints } from '@/services/endpoints'
import type { LogEntry } from '../types'

/**
 * Fetches the initial log buffer from the REST API and writes entries to the
 * xterm.js terminal. Also populates the shared entries ref so the parent can
 * re-render when the level filter changes.
 */
export function useLogBufferInit(
  terminal: Terminal | null,
  allEntriesRef: MutableRefObject<LogEntry[]>,
  options: {
    levelFilter: number
    onCountUpdate: (count: number) => void
  }
) {
  const fetchedRef = useRef(false)

  useEffect(() => {
    if (!terminal || fetchedRef.current) return
    fetchedRef.current = true

    let cancelled = false

    async function fetchBuffer() {
      try {
        const entries = await api.get<LogEntry[]>(apiEndpoints.debug.logs)
        if (cancelled || !terminal) return

        // Store all entries for later re-filtering
        allEntriesRef.current = entries

        let count = 0
        for (const entry of entries) {
          if (entry.levelNo >= options.levelFilter) {
            terminal.writeln(entry.formatted)
            count++
          }
        }
        options.onCountUpdate(count)
      } catch {
        // Best-effort — the terminal still works with just WS streaming
      }
    }

    fetchBuffer()

    return () => {
      cancelled = true
    }
    // Only run once on mount with the terminal instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminal])
}
