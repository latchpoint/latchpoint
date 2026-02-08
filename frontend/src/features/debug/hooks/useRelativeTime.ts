import { useReducer, useEffect } from 'react'

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

function formatRelative(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime()

  if (diff < 0) return 'just now'
  if (diff < 5 * SECOND) return 'just now'
  if (diff < MINUTE) return `${Math.floor(diff / SECOND)}s ago`
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`
  return `${Math.floor(diff / DAY)}d ago`
}

export function useRelativeTime(timestamp: string | null): string {
  const [, forceUpdate] = useReducer((n: number) => n + 1, 0)

  useEffect(() => {
    if (!timestamp) return

    const diff = Date.now() - new Date(timestamp).getTime()
    const interval = diff < MINUTE ? SECOND : 30 * SECOND

    const id = setInterval(forceUpdate, interval)
    return () => clearInterval(id)
  }, [timestamp, forceUpdate])

  return timestamp ? formatRelative(timestamp) : '—'
}
