import { Activity } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { AlarmEvent } from '@/types'
import { eventConfig } from '@/features/events/constants/eventPresentation'
import { formatEventTimeAbsolute, formatEventTimeRelative } from '@/features/events/utils/dateTime'
import { getMetadataSummary } from '@/features/events/utils/eventMetadata'

export function EventRow({ event }: { event: AlarmEvent }) {
  const config = eventConfig[event.eventType] || {
    icon: Activity,
    colorClassName: 'text-muted-foreground',
    label: event.eventType,
  }
  const Icon = config.icon

  const metaSummary = getMetadataSummary(event.metadata)
  const details = [
    event.stateTo ? `${event.stateFrom ? `${event.stateFrom} → ` : ''}${event.stateTo}` : null,
    event.sensorId ? `sensor #${event.sensorId}` : null,
    event.userId ? `user ${event.userId}` : null,
    metaSummary ? `meta: ${metaSummary}` : null,
  ].filter(Boolean)

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg hover:bg-muted/50 transition-colors">
      <div className={cn('shrink-0 mt-0.5', config.colorClassName)}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-3">
          <div className="font-medium truncate">{config.label}</div>
          <Tooltip content={formatEventTimeAbsolute(event.timestamp)}>
            <div className="text-sm text-muted-foreground shrink-0">{formatEventTimeRelative(event.timestamp)}</div>
          </Tooltip>
        </div>
        {details.length > 0 ? <div className="text-sm text-muted-foreground truncate">{details.join(' • ')}</div> : null}
      </div>
    </div>
  )
}

