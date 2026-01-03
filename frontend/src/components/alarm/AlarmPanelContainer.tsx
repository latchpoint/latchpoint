import { useCallback } from 'react'
import type { AlarmStateType } from '@/lib/constants'
import { useAlarmState } from '@/hooks/useAlarmState'
import { useAlarmActions } from '@/hooks/useAlarmActions'
import { useAlarmValidation } from '@/hooks/useAlarmValidation'
import { useRecentEventsQuery } from '@/hooks/useAlarmQueries'
import { useModal } from '@/stores/modalStore'
import { handleError } from '@/lib/errorHandler'
import { AlarmPanelView } from './AlarmPanelView'

interface AlarmPanelContainerProps {
  className?: string
}

/**
 * Container component for the alarm panel.
 * Handles all business logic, data fetching, and side effects.
 * Uses the modal system for code entry instead of inline modals.
 */
export function AlarmPanelContainer({ className }: AlarmPanelContainerProps) {
  const state = useAlarmState()
  const { arm, disarm, cancelArming, isPending } = useAlarmActions()
  const { openSensors, unknownSensors } = useAlarmValidation()
  const recentEventsQuery = useRecentEventsQuery()
  const { open: openCodeEntry } = useModal('code-entry')

  const handleArm = useCallback(
    (targetState: AlarmStateType) => {
      if (state.codeRequiredForArm) {
        openCodeEntry({
          title: 'Enter Code to Arm',
          submitLabel: 'Arm',
          onSubmit: (code) => arm(targetState, code),
        })
      } else {
        arm(targetState).catch((error) => {
          handleError(error)
        })
      }
    },
    [state.codeRequiredForArm, arm, openCodeEntry]
  )

  const handleDisarm = useCallback(() => {
    openCodeEntry({
      title: 'Enter Code to Disarm',
      submitLabel: 'Disarm',
      onSubmit: disarm,
    })
  }, [disarm, openCodeEntry])

  const handleCancelArming = useCallback(async () => {
    try {
      await cancelArming()
    } catch (error) {
      handleError(error)
    }
  }, [cancelArming])

  return (
    <AlarmPanelView
      className={className}
      currentState={state.currentState}
      countdown={state.countdown}
      isArmed={state.isArmed}
      isDisarmed={state.isDisarmed}
      isArming={state.isArming}
      isPending={state.isPending}
      isTriggered={state.isTriggered}
      availableArmingStates={state.availableArmingStates}
      isLoading={state.isLoading || isPending}
      recentEvents={recentEventsQuery.data ?? []}
      openSensors={openSensors}
      unknownSensors={unknownSensors}
      onArm={handleArm}
      onDisarm={handleDisarm}
      onCancelArming={handleCancelArming}
    />
  )
}
