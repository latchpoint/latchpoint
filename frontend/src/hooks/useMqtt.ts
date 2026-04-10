import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

export function useUpdateMqttSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      enabled?: boolean
      keepaliveSeconds?: number
      connectTimeoutSeconds?: number
    }) => mqttService.updateSettings(data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.mqtt.settings })
      await queryClient.invalidateQueries({ queryKey: queryKeys.mqtt.status })
    },
  })
}
