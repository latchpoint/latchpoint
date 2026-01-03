import { useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlarmState } from '@/lib/constants'
import type { AlarmStateType } from '@/lib/constants'
import { alarmService } from '@/services'
import { queryKeys } from '@/types'
import { getErrorMessage } from '@/types/errors'

export interface UseAlarmActionsReturn {
  // Core actions
  arm: (targetState: AlarmStateType, code?: string) => Promise<void>
  disarm: (code: string) => Promise<void>
  cancelArming: (code?: string) => Promise<void>

  // Convenience wrappers
  armHome: (code?: string) => Promise<void>
  armAway: (code?: string) => Promise<void>
  armNight: (code?: string) => Promise<void>
  armVacation: (code?: string) => Promise<void>

  // Utilities
  refresh: () => void
  clearError: () => void

  // Status
  isPending: boolean
  error: string | null
}

/**
 * Alarm action mutations hook.
 * Provides all mutation operations for alarm control (arm, disarm, cancel).
 */
export function useAlarmActions(): UseAlarmActionsReturn {
  const queryClient = useQueryClient()

  const armMutation = useMutation({
    mutationFn: ({ targetState, code }: { targetState: AlarmStateType; code?: string }) =>
      alarmService.arm({ targetState, code }),
    onSuccess: (nextState) => {
      queryClient.setQueryData(queryKeys.alarm.state, nextState)
      void queryClient.invalidateQueries({ queryKey: queryKeys.events.recent })
    },
  })

  const disarmMutation = useMutation({
    mutationFn: ({ code }: { code: string }) => alarmService.disarm({ code }),
    onSuccess: (nextState) => {
      queryClient.setQueryData(queryKeys.alarm.state, nextState)
      queryClient.setQueryData(queryKeys.alarm.countdown, null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.events.recent })
    },
  })

  const cancelArmingMutation = useMutation({
    mutationFn: ({ code }: { code?: string }) => alarmService.cancelArming(code),
    onSuccess: (nextState) => {
      queryClient.setQueryData(queryKeys.alarm.state, nextState)
      queryClient.setQueryData(queryKeys.alarm.countdown, null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.events.recent })
    },
  })

  // Combined status
  const isPending =
    armMutation.isPending || disarmMutation.isPending || cancelArmingMutation.isPending

  const error =
    (armMutation.error && getErrorMessage(armMutation.error, '')) ||
    (disarmMutation.error && getErrorMessage(disarmMutation.error, '')) ||
    (cancelArmingMutation.error && getErrorMessage(cancelArmingMutation.error, '')) ||
    null

  // Core actions
  const arm = useCallback(
    async (targetState: AlarmStateType, code?: string) => {
      await armMutation.mutateAsync({ targetState, code })
    },
    [armMutation]
  )

  const disarm = useCallback(
    async (code: string) => {
      await disarmMutation.mutateAsync({ code })
    },
    [disarmMutation]
  )

  const cancelArming = useCallback(
    async (code?: string) => {
      await cancelArmingMutation.mutateAsync({ code })
    },
    [cancelArmingMutation]
  )

  // Convenience wrappers
  const armHome = useCallback((code?: string) => arm(AlarmState.ARMED_HOME, code), [arm])
  const armAway = useCallback((code?: string) => arm(AlarmState.ARMED_AWAY, code), [arm])
  const armNight = useCallback((code?: string) => arm(AlarmState.ARMED_NIGHT, code), [arm])
  const armVacation = useCallback(
    (code?: string) => arm(AlarmState.ARMED_VACATION, code),
    [arm]
  )

  // Utilities
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.alarm.state })
    void queryClient.invalidateQueries({ queryKey: queryKeys.sensors.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.events.recent })
  }, [queryClient])

  const clearError = useCallback(() => {
    armMutation.reset()
    disarmMutation.reset()
    cancelArmingMutation.reset()
  }, [armMutation, disarmMutation, cancelArmingMutation])

  return {
    arm,
    disarm,
    cancelArming,
    armHome,
    armAway,
    armNight,
    armVacation,
    refresh,
    clearError,
    isPending,
    error,
  }
}
