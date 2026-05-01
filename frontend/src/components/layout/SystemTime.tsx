import { useEffect, useMemo, useState } from 'react'
import { Clock } from 'lucide-react'

import { Tooltip } from '@/components/ui/tooltip'
import { useServerTimeQuery } from '@/hooks/useServerTime'
import { cn } from '@/lib/utils'

const STALE_THRESHOLD_MS = 10 * 60_000

interface SystemTimeProps {
  collapsed: boolean
}

export function SystemTime({ collapsed }: SystemTimeProps) {
  const { data, dataUpdatedAt } = useServerTimeQuery()
  const [tickNow, setTickNow] = useState(() => Date.now())

  useEffect(() => {
    const intervalMs = collapsed ? 60_000 : 1000
    let intervalId: number | undefined

    const start = () => {
      if (intervalId !== undefined) return
      setTickNow(Date.now())
      intervalId = window.setInterval(() => setTickNow(Date.now()), intervalMs)
    }

    const stop = () => {
      if (intervalId === undefined) return
      window.clearInterval(intervalId)
      intervalId = undefined
    }

    const handleVisibility = () => {
      if (document.hidden) stop()
      else start()
    }

    if (!document.hidden) start()
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      stop()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [collapsed])

  // Build formatters with the *server's* IANA timezone but the *browser's*
  // locale defaults (dateStyle/timeStyle). The explicit timeZone is what
  // defeats Intl's silent fallback to the browser's local zone — that fallback
  // is the JS Date footgun this whole feature exists to defend against.
  const formatters = useMemo(() => {
    const buildFormatters = (resolvedTimeZone: string | undefined) => ({
      full: new Intl.DateTimeFormat(undefined, {
        timeZone: resolvedTimeZone,
        dateStyle: 'short',
        timeStyle: 'long',
      }),
      short: new Intl.DateTimeFormat(undefined, {
        timeZone: resolvedTimeZone,
        timeStyle: 'short',
      }),
    })

    // A misconfigured server `TIME_ZONE` (invalid IANA string) would make
    // `Intl.DateTimeFormat` throw RangeError and crash the sidebar. Fall back
    // to UTC so the clock still renders — the wrong-zone tradeoff is loud
    // (UTC is obvious to anyone watching) but not catastrophic.
    try {
      return buildFormatters(data?.timezone)
    } catch {
      return buildFormatters('UTC')
    }
  }, [data?.timezone])

  if (!data) {
    return collapsed ? <PlaceholderCollapsed /> : <PlaceholderExpanded />
  }

  const offsetMs = data.epochMs - dataUpdatedAt
  const serverNow = new Date(tickNow + offsetMs)
  const stale = tickNow - dataUpdatedAt > STALE_THRESHOLD_MS

  if (collapsed) {
    const fullTime = formatters.full.format(serverNow)
    return (
      <div className="flex justify-center">
        <Tooltip content={fullTime} side="right">
          <span
            tabIndex={0}
            aria-label={fullTime}
            className={cn(
              'flex items-center gap-1.5 text-xs text-muted-foreground rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
              stale && 'opacity-60'
            )}
          >
            <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="tabular-nums">{formatters.short.format(serverNow)}</span>
          </span>
        </Tooltip>
      </div>
    )
  }

  return (
    <div className={cn('text-xs text-muted-foreground px-1', stale && 'opacity-60')}>
      <div className="flex min-w-0 items-center gap-1.5">
        <Clock className="h-3 w-3 shrink-0" />
        <span className="tabular-nums truncate">{formatters.full.format(serverNow)}</span>
      </div>
    </div>
  )
}

function PlaceholderCollapsed() {
  return (
    <div className="flex justify-center">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Clock className="h-3 w-3 shrink-0" />
        <span className="tabular-nums">--:--</span>
      </span>
    </div>
  )
}

function PlaceholderExpanded() {
  return (
    <div className="text-xs text-muted-foreground px-1">
      <div className="flex min-w-0 items-center gap-1.5">
        <Clock className="h-3 w-3 shrink-0" />
        <span className="tabular-nums">--:--:--</span>
      </div>
    </div>
  )
}

export default SystemTime
