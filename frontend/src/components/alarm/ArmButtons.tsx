import { Home, Shield, Moon, Plane } from 'lucide-react'
import { AlarmState, type AlarmStateType } from '@/lib/constants'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface ArmButtonsProps {
  onArm: (state: AlarmStateType) => void
  availableStates?: AlarmStateType[]
  currentState: AlarmStateType
  disabled?: boolean
  className?: string
}

const armStateConfig: Record<
  string,
  {
    icon: React.ElementType
    label: string
    color: string
  }
> = {
  [AlarmState.ARMED_HOME]: {
    icon: Home,
    label: 'Home',
    color: 'bg-alarm-armed-home hover:bg-alarm-armed-home/90',
  },
  [AlarmState.ARMED_AWAY]: {
    icon: Shield,
    label: 'Away',
    color: 'bg-alarm-armed-away hover:bg-alarm-armed-away/90',
  },
  [AlarmState.ARMED_NIGHT]: {
    icon: Moon,
    label: 'Night',
    color: 'bg-alarm-armed-night hover:bg-alarm-armed-night/90',
  },
  [AlarmState.ARMED_VACATION]: {
    icon: Plane,
    label: 'Vacation',
    color: 'bg-alarm-armed-vacation hover:bg-alarm-armed-vacation/90',
  },
}

export function ArmButtons({
  onArm,
  availableStates = [
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
  ],
  currentState,
  disabled = false,
  className,
}: ArmButtonsProps) {

  return (
    <div className={cn('grid grid-cols-2 gap-3', className)}>
      {availableStates.map((state) => {
        const config = armStateConfig[state]
        if (!config) return null

        const Icon = config.icon
        const isCurrentState = currentState === state

        return (
          <Button
            key={state}
            variant="default"
            className={cn(
              'h-20 flex-col gap-1 text-white',
              config.color,
              isCurrentState && 'ring-2 ring-offset-2 ring-offset-background',
              disabled && 'opacity-50'
            )}
            onClick={() => onArm(state)}
            disabled={disabled || isCurrentState}
          >
            <Icon className="h-6 w-6" />
            <span className="text-sm font-medium">{config.label}</span>
          </Button>
        )
      })}
    </div>
  )
}

export default ArmButtons
