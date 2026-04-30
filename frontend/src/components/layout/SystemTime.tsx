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
  const { data, dataUpdatedAt, isSuccess } = useServerTimeQuery()
  const [tickNow, setTickNow] = useState(() => Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setTickNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  // Build formatters with the *server's* IANA timezone. Without an explicit
  // timeZone option, Intl falls back to the browser's local zone — which would
  // silently render the wrong wall-clock for any user not co-located with the
  // server. This option is the entire point of the feature.
  const formatters = useMemo(() => {
    const timeZone = data?.timezone
    return {
      full: new Intl.DateTimeFormat(undefined, {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
        timeZoneName: 'short',
      }),
      short: new Intl.DateTimeFormat(undefined, {
        timeZone,
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }),
    }
  }, [data?.timezone])

  if (!isSuccess || !data) {
    return collapsed ? <PlaceholderCollapsed /> : <PlaceholderExpanded />
  }

  const offsetMs = data.epochMs - dataUpdatedAt
  const serverNow = new Date(tickNow + offsetMs)
  const stale = tickNow - dataUpdatedAt > STALE_THRESHOLD_MS

  if (collapsed) {
    return (
      <div className="flex justify-center">
        <Tooltip content={formatters.full.format(serverNow)} side="right">
          <span
            className={cn(
              'flex items-center gap-1.5 text-xs text-muted-foreground',
              stale && 'opacity-60'
            )}
          >
            <Clock className="h-3 w-3 shrink-0" />
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
