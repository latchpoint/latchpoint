import { useMemo } from 'react'
import type { AlarmEvent } from '@/types'
import { useWebSocketStatus } from '@/hooks/useWebSocketStatus'
import { useRecentEventsQuery } from '@/hooks/useAlarmQueries'
import { useAlarmState as useAlarmStateHook } from '@/hooks/useAlarmState'
import { useAlarmActions as useAlarmActionsHook } from '@/hooks/useAlarmActions'
import { useAlarmValidation as useAlarmValidationHook } from '@/hooks/useAlarmValidation'
import { getErrorMessage } from '@/types/errors'

/**
 * Main alarm hook - facade that composes focused hooks.
 * Maintains backward compatibility while delegating to smaller, focused hooks.
 *
 * @deprecated Consider using focused hooks directly:
 * - useAlarmState() for read-only state
 * - useAlarmActions() for mutations
 * - useAlarmValidation() for sensor validation
 */
export function useAlarm() {
  const state = useAlarmStateHook()
  const actions = useAlarmActionsHook()
  const validation = useAlarmValidationHook()
  const wsStatusQuery = useWebSocketStatus()
  const recentEventsQuery = useRecentEventsQuery()

  const recentEvents: AlarmEvent[] = useMemo(
    () => recentEventsQuery.data ?? [],
    [recentEventsQuery.data]
  )

  // Combine loading states
  const isLoading =
    state.isLoading ||
    validation.isLoading ||
    actions.isPending ||
    recentEventsQuery.isLoading

  // Combine errors (actions.error takes precedence)
  const error =
    actions.error ||
    (recentEventsQuery.error && getErrorMessage(recentEventsQuery.error, '')) ||
    null

  // Return combined interface for backward compatibility
  return {
    // From useAlarmState
    alarmState: state.alarmState,
    currentState: state.currentState,
    settings: state.settings,
    countdown: state.countdown,
    isArmed: state.isArmed,
    isDisarmed: state.isDisarmed,
    isArming: state.isArming,
    isPending: state.isPending,
    isTriggered: state.isTriggered,
    codeRequiredForArm: state.codeRequiredForArm,
    availableArmingStates: state.availableArmingStates,

    // From useAlarmValidation
    sensors: validation.sensors,
    openSensors: validation.openSensors,
    unknownSensors: validation.unknownSensors,
    canArm: validation.canArm,

    // From useAlarmActions
    arm: actions.arm,
    armHome: actions.armHome,
    armAway: actions.armAway,
    armNight: actions.armNight,
    armVacation: actions.armVacation,
    disarm: actions.disarm,
    cancelArming: actions.cancelArming,
    clearError: actions.clearError,
    refresh: actions.refresh,

    // Additional queries
    recentEvents,
    wsStatus: wsStatusQuery.data,

    // Combined status
    isLoading,
    error,
  }
}

// Re-export useAlarmState for convenience
export { useAlarmState } from '@/hooks/useAlarmState'

export default useAlarm
