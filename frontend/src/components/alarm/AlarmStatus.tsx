import {
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  Home,
  Moon,
  Plane,
  AlertTriangle,
  Clock,
} from 'lucide-react'
import { AlarmState, AlarmStateLabels, type AlarmStateType } from '@/lib/constants'
import { cn } from '@/lib/utils'

interface AlarmStatusProps {
  state: AlarmStateType
  className?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  showLabel?: boolean
  animate?: boolean
}

const stateConfig: Record<
  AlarmStateType,
  {
    icon: React.ElementType
    bgColor: string
    textColor: string
    borderColor: string
    pulseColor?: string
  }
> = {
  [AlarmState.DISARMED]: {
    icon: ShieldOff,
    bgColor: 'bg-alarm-disarmed',
    textColor: 'text-alarm-disarmed',
    borderColor: 'border-alarm-disarmed',
  },
  [AlarmState.ARMING]: {
    icon: Clock,
    bgColor: 'bg-alarm-arming',
    textColor: 'text-alarm-arming',
    borderColor: 'border-alarm-arming',
    pulseColor: 'bg-alarm-arming/80',
  },
  [AlarmState.ARMED_HOME]: {
    icon: Home,
    bgColor: 'bg-alarm-armed-home',
    textColor: 'text-alarm-armed-home',
    borderColor: 'border-alarm-armed-home',
  },
  [AlarmState.ARMED_AWAY]: {
    icon: ShieldCheck,
    bgColor: 'bg-alarm-armed-away',
    textColor: 'text-alarm-armed-away',
    borderColor: 'border-alarm-armed-away',
  },
  [AlarmState.ARMED_NIGHT]: {
    icon: Moon,
    bgColor: 'bg-alarm-armed-night',
    textColor: 'text-alarm-armed-night',
    borderColor: 'border-alarm-armed-night',
  },
  [AlarmState.ARMED_VACATION]: {
    icon: Plane,
    bgColor: 'bg-alarm-armed-vacation',
    textColor: 'text-alarm-armed-vacation',
    borderColor: 'border-alarm-armed-vacation',
  },
  [AlarmState.ARMED_CUSTOM_BYPASS]: {
    icon: ShieldCheck,
    bgColor: 'bg-muted-foreground',
    textColor: 'text-muted-foreground',
    borderColor: 'border-muted-foreground',
  },
  [AlarmState.PENDING]: {
    icon: AlertTriangle,
    bgColor: 'bg-alarm-pending',
    textColor: 'text-alarm-pending',
    borderColor: 'border-alarm-pending',
    pulseColor: 'bg-alarm-pending/80',
  },
  [AlarmState.TRIGGERED]: {
    icon: ShieldAlert,
    bgColor: 'bg-alarm-triggered',
    textColor: 'text-alarm-triggered',
    borderColor: 'border-alarm-triggered',
    pulseColor: 'bg-danger',
  },
}

const sizeClasses = {
  sm: 'h-12 w-12',
  md: 'h-16 w-16',
  lg: 'h-24 w-24',
  xl: 'h-32 w-32',
}

const iconSizes = {
  sm: 'h-6 w-6',
  md: 'h-8 w-8',
  lg: 'h-12 w-12',
  xl: 'h-16 w-16',
}

const labelSizes = {
  sm: 'text-sm',
  md: 'text-base',
  lg: 'text-xl',
  xl: 'text-2xl',
}

export function AlarmStatus({
  state,
  className,
  size = 'lg',
  showLabel = true,
  animate = true,
}: AlarmStatusProps) {
  const config = stateConfig[state]
  const Icon = config.icon
  const shouldPulse = animate && config.pulseColor

  return (
    <div className={cn('flex flex-col items-center gap-3', className)}>
      {/* Status Circle */}
      <div className="relative">
        {/* Pulse animation for certain states */}
        {shouldPulse && (
          <div
            className={cn(
              'absolute inset-0 rounded-full animate-ping opacity-75',
              config.pulseColor,
              sizeClasses[size]
            )}
          />
        )}
        <div
          className={cn(
            'relative flex items-center justify-center rounded-full text-white',
            config.bgColor,
            sizeClasses[size],
            shouldPulse && 'animate-pulse'
          )}
        >
          <Icon className={iconSizes[size]} />
        </div>
      </div>

      {/* Label */}
      {showLabel && (
        <div className="text-center">
          <p className={cn('font-bold', labelSizes[size], config.textColor)}>
            {AlarmStateLabels[state]}
          </p>
        </div>
      )}
    </div>
  )
}

export default AlarmStatus
