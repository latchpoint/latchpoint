import { useQuery } from '@tanstack/react-query'
import { mqttService } from '@/services'
import { queryKeys } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'

export function useMqttStatusQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.mqtt.status,
    queryFn: mqttService.getStatus,
    enabled: isAuthenticated,
  })
}

export function useMqttSettingsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.mqtt.settings,
    queryFn: mqttService.getSettings,
    enabled: isAuthenticated && isAdmin,
  })
}
