import { Activity, AlertTriangle, Key, Shield, ShieldAlert, ShieldOff } from 'lucide-react'
import type { ElementType } from 'react'
import { EventType } from '@/lib/constants'

export const eventTypeOptions: { value: string; label: string }[] = [
  { value: '', label: 'All events' },
  { value: EventType.ARMED, label: 'Armed' },
  { value: EventType.DISARMED, label: 'Disarmed' },
  { value: EventType.PENDING, label: 'Entry delay' },
  { value: EventType.TRIGGERED, label: 'Triggered' },
  { value: EventType.CODE_USED, label: 'Code used' },
  { value: EventType.FAILED_CODE, label: 'Failed code' },
  { value: EventType.SENSOR_TRIGGERED, label: 'Sensor triggered' },
  { value: EventType.STATE_CHANGED, label: 'State changed' },
]

export const eventConfig: Record<
  string,
  {
    icon: ElementType
    colorClassName: string
    label: string
  }
> = {
  [EventType.ARMED]: {
    icon: Shield,
    colorClassName: 'text-[color:var(--color-alarm-armed-away)]',
    label: 'Armed',
  },
  [EventType.DISARMED]: {
    icon: ShieldOff,
    colorClassName: 'text-[color:var(--color-alarm-disarmed)]',
    label: 'Disarmed',
  },
  [EventType.TRIGGERED]: {
    icon: ShieldAlert,
    colorClassName: 'text-[color:var(--color-alarm-triggered)]',
    label: 'Triggered',
  },
  [EventType.CODE_USED]: { icon: Key, colorClassName: 'text-primary', label: 'Code used' },
  [EventType.SENSOR_TRIGGERED]: {
    icon: Activity,
    colorClassName: 'text-[color:var(--color-alarm-pending)]',
    label: 'Sensor triggered',
  },
  [EventType.FAILED_CODE]: {
    icon: AlertTriangle,
    colorClassName: 'text-[color:var(--color-alarm-armed-home)]',
    label: 'Failed code',
  },
  [EventType.PENDING]: {
    icon: AlertTriangle,
    colorClassName: 'text-[color:var(--color-alarm-pending)]',
    label: 'Entry delay',
  },
  [EventType.STATE_CHANGED]: { icon: Shield, colorClassName: 'text-muted-foreground', label: 'State changed' },
}
