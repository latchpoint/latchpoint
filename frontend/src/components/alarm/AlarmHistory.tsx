import { formatDistanceToNow } from 'date-fns'
import {
  Shield,
  ShieldOff,
  ShieldAlert,
  Key,
  AlertTriangle,
  Activity,
} from 'lucide-react'
import { DEFAULT_RECENT_EVENTS_LIMIT, EventType } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type { AlarmEvent } from '@/types'

interface AlarmHistoryProps {
  events: AlarmEvent[]
  maxItems?: number
  className?: string
}

const eventConfig: Record<
  string,
  {
    icon: React.ElementType
    color: string
    label: string
  }
> = {
  [EventType.ARMED]: {
    icon: Shield,
    color: 'text-danger',
    label: 'Armed',
  },
  [EventType.DISARMED]: {
    icon: ShieldOff,
    color: 'text-success',
    label: 'Disarmed',
  },
  [EventType.TRIGGERED]: {
    icon: ShieldAlert,
    color: 'text-critical',
    label: 'Triggered',
  },
  [EventType.CODE_USED]: {
    icon: Key,
    color: 'text-info',
    label: 'Code Used',
  },
  [EventType.SENSOR_TRIGGERED]: {
    icon: Activity,
    color: 'text-warning',
    label: 'Sensor Triggered',
  },
  [EventType.FAILED_CODE]: {
    icon: AlertTriangle,
    color: 'text-warning',
    label: 'Failed Code',
  },
  [EventType.PENDING]: {
    icon: AlertTriangle,
    color: 'text-warning',
    label: 'Entry Delay',
  },
  [EventType.STATE_CHANGED]: {
    icon: Shield,
    color: 'text-muted-foreground',
    label: 'State Changed',
  },
}

function formatEventTime(timestamp: string): string {
  try {
    return formatDistanceToNow(new Date(timestamp), { addSuffix: true })
  } catch {
    return timestamp
  }
}

export function AlarmHistory({
  events,
  maxItems = DEFAULT_RECENT_EVENTS_LIMIT,
  className,
}: AlarmHistoryProps) {
  const displayEvents = events.slice(0, maxItems)

  if (displayEvents.length === 0) {
    return (
      <div className={cn('text-center py-8 text-muted-foreground', className)}>
        <Activity className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p>No recent activity</p>
      </div>
    )
  }

  return (
    <div className={cn('space-y-1', className)}>
      {displayEvents.map((event) => {
        const config = eventConfig[event.eventType] || {
          icon: Activity,
          color: 'text-muted-foreground',
          label: event.eventType,
        }
        const Icon = config.icon

        return (
          <div
            key={event.id}
            className="flex items-center gap-3 p-3 rounded-lg hover:bg-muted/50 transition-colors"
          >
            <div className={cn('shrink-0', config.color)}>
              <Icon className="h-5 w-5" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-medium truncate">{config.label}</p>
              {event.stateTo && (
                <p className="text-sm text-muted-foreground truncate">
                  {event.stateFrom ? `${event.stateFrom} → ` : ''}
                  {event.stateTo}
                </p>
              )}
            </div>
            <div className="text-sm text-muted-foreground shrink-0">
              {formatEventTime(event.timestamp)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default AlarmHistory
