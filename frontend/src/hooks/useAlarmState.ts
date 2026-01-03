import { useQuery } from '@tanstack/react-query'
import { AlarmState } from '@/lib/constants'
import type { AlarmStateType } from '@/lib/constants'
import type { AlarmStateSnapshot, AlarmSettingsProfile, CountdownPayload } from '@/types'
import { queryKeys } from '@/types'
import { useAlarmStateQuery, useAlarmSettingsQuery } from '@/hooks/useAlarmQueries'

export interface UseAlarmStateReturn {
  // Raw data
  alarmState: AlarmStateSnapshot | null
  settings: AlarmSettingsProfile | null
  countdown: CountdownPayload | null

  // Derived flags
  currentState: AlarmStateType
  isArmed: boolean
  isDisarmed: boolean
  isArming: boolean
  isPending: boolean
  isTriggered: boolean

  // Config from settings
  codeRequiredForArm: boolean
  availableArmingStates: AlarmStateType[]

  // Status
  isLoading: boolean
}

/**
 * Read-only alarm state hook.
 * Provides alarm state, settings, and derived flags without mutations.
 */
export function useAlarmState(): UseAlarmStateReturn {
  const alarmStateQuery = useAlarmStateQuery()
  const settingsQuery = useAlarmSettingsQuery()

  // Countdown is passive (updated via WebSocket)
  const countdownQuery = useQuery<CountdownPayload | null>({
    queryKey: queryKeys.alarm.countdown,
    queryFn: async () => null,
    initialData: null,
    enabled: false,
  })

  const alarmState = alarmStateQuery.data ?? null
  const settings = settingsQuery.data ?? null
  const countdown = countdownQuery.data ?? null

  const isLoading = alarmStateQuery.isLoading || settingsQuery.isLoading

  // Derive current state
  const currentState = alarmState?.currentState ?? AlarmState.DISARMED

  // Derive state flags
  const armedStates: string[] = [
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
  ]
  const isArmed = armedStates.includes(currentState)
  const isDisarmed = currentState === AlarmState.DISARMED
  const isArming = currentState === AlarmState.ARMING
  const isPending = currentState === AlarmState.PENDING
  const isTriggered = currentState === AlarmState.TRIGGERED

  // Config from settings
  const codeRequiredForArm = settings?.codeArmRequired ?? true
  const availableArmingStates = settings?.availableArmingStates ?? [
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
  ]

  return {
    alarmState,
    settings,
    countdown,
    currentState,
    isArmed,
    isDisarmed,
    isArming,
    isPending,
    isTriggered,
    codeRequiredForArm,
    availableArmingStates,
    isLoading,
  }
}
