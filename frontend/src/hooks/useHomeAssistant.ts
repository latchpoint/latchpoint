import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { homeAssistantService } from '@/services'
import { queryKeys } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'
import type { HomeAssistantConnectionSettingsUpdate } from '@/services/homeAssistant'

export function useHomeAssistantStatus() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.homeAssistant.status,
    queryFn: homeAssistantService.getStatus,
    enabled: isAuthenticated,
  })
}

export function useHomeAssistantSettingsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.homeAssistant.settings,
    queryFn: homeAssistantService.getSettings,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useUpdateHomeAssistantSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: HomeAssistantConnectionSettingsUpdate) =>
      homeAssistantService.updateSettings(changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.homeAssistant.settings })
      await queryClient.invalidateQueries({ queryKey: queryKeys.homeAssistant.status })
      await queryClient.invalidateQueries({ queryKey: queryKeys.homeAssistant.entities })
      await queryClient.invalidateQueries({ queryKey: queryKeys.homeAssistant.notifyServices })
    },
  })
}

export function useHomeAssistantEntities() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const statusQuery = useHomeAssistantStatus()
  const enabled = !!isAuthenticated && !!statusQuery.data?.configured && !!statusQuery.data?.reachable

  return useQuery({
    queryKey: queryKeys.homeAssistant.entities,
    queryFn: homeAssistantService.listEntities,
    enabled,
  })
}

export function useHomeAssistantNotifyServices() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const statusQuery = useHomeAssistantStatus()
  const enabled = !!isAuthenticated && !!statusQuery.data?.configured && !!statusQuery.data?.reachable

  return useQuery({
    queryKey: queryKeys.homeAssistant.notifyServices,
    queryFn: homeAssistantService.listNotifyServices,
    enabled,
  })
}

export default useHomeAssistantStatus
