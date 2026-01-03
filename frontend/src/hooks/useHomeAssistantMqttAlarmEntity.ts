import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { integrationsService } from '@/services'
import { queryKeys } from '@/types'
import type { HomeAssistantMqttAlarmEntitySettingsUpdate } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'

export function useHomeAssistantMqttAlarmEntitySettingsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.integrations.homeAssistantMqttAlarmEntity,
    queryFn: integrationsService.homeAssistantMqttAlarmEntity.getSettings,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useHomeAssistantMqttAlarmEntityStatusQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.integrations.homeAssistantMqttAlarmEntityStatus,
    queryFn: integrationsService.homeAssistantMqttAlarmEntity.getStatus,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useUpdateHomeAssistantMqttAlarmEntitySettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: HomeAssistantMqttAlarmEntitySettingsUpdate) =>
      integrationsService.homeAssistantMqttAlarmEntity.updateSettings(changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.integrations.homeAssistantMqttAlarmEntity })
      await queryClient.invalidateQueries({ queryKey: queryKeys.integrations.homeAssistantMqttAlarmEntityStatus })
    },
  })
}

export function usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => integrationsService.homeAssistantMqttAlarmEntity.publishDiscovery(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.integrations.homeAssistantMqttAlarmEntityStatus })
    },
  })
}

