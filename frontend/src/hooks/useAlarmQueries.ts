import { useQuery } from '@tanstack/react-query'
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
