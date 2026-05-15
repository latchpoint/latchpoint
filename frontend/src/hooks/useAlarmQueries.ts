import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { alarmService, sensorsService } from '@/services'
import { queryKeys } from '@/types'
import { useAuthSessionQuery } from '@/hooks/useAuthQueries'
import { DEFAULT_RECENT_EVENTS_LIMIT } from '@/lib/constants'

export function useAlarmStateQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.alarm.state,
    queryFn: alarmService.getState,
    enabled: isAuthenticated,
  })
}

export function useAlarmSettingsQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.alarm.settings,
    queryFn: alarmService.getSettings,
    enabled: isAuthenticated,
  })
}

export function useSensorsQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.sensors.all,
    queryFn: sensorsService.getSensors,
    enabled: isAuthenticated,
  })
}

export function useRecentEventsQuery(limit = DEFAULT_RECENT_EVENTS_LIMIT) {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.events.recent,
    queryFn: () => alarmService.getRecentEvents(limit),
    enabled: isAuthenticated,
  })
}

// ADR-0091: PendingAction queue
export function usePendingActionsQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.alarm.pendingActions,
    queryFn: () => alarmService.getPendingActions({ status: 'scheduled' }),
    enabled: isAuthenticated,
    refetchInterval: 2000,
  })
}

export function useCancelPendingActionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => alarmService.cancelPendingAction(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.alarm.pendingActions })
    },
  })
}
