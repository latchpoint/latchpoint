/**
 * Custom value editor for alarm_state_in condition
 * Allows multi-select of alarm states
 */
import type { ValueEditorProps } from 'react-querybuilder'
import { ALARM_STATES, type AlarmStateValue } from '../types'
import { cn } from '@/lib/utils'

export function AlarmStateValueEditor({ value, handleOnChange, disabled }: ValueEditorProps) {
  const currentValue = (value as AlarmStateValue) || { states: [] }
  const selectedStates = new Set(currentValue.states || [])

  const toggleState = (stateName: string) => {
    const newStates = new Set(selectedStates)
    if (newStates.has(stateName)) {
      newStates.delete(stateName)
    } else {
      newStates.add(stateName)
    }
    handleOnChange({ states: Array.from(newStates) } as AlarmStateValue)
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {ALARM_STATES.map((state) => (
        <button
          key={state.name}
          type="button"
          disabled={disabled}
          onClick={() => toggleState(state.name)}
          className={cn(
            'rounded-md px-2 py-1 text-xs font-medium transition-colors',
            'border',
            selectedStates.has(state.name)
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-input bg-background hover:bg-accent hover:text-accent-foreground',
            disabled && 'cursor-not-allowed opacity-50'
          )}
        >
          {state.label}
        </button>
      ))}
    </div>
  )
}
