import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { zwavejsService } from '@/services'
import { queryKeys } from '@/types'
import type { ZwavejsSettingsUpdate, ZwavejsTestConnectionRequest } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { TEN_SECONDS_MS, UserRole } from '@/lib/constants'
import { formatEntitiesSyncNotice } from '@/lib/notices'

export function useZwavejsStatusQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.zwavejs.status,
    queryFn: zwavejsService.getStatus,
    enabled: isAuthenticated,
  })
}

export function useZwavejsNodesQuery(params?: { enabled?: boolean }) {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.zwavejs.nodes,
    queryFn: zwavejsService.getNodes,
    enabled: (params?.enabled ?? true) && isAuthenticated && isAdmin,
    staleTime: TEN_SECONDS_MS,
  })
}

export function useZwavejsSettingsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.zwavejs.settings,
    queryFn: zwavejsService.getSettings,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useUpdateZwavejsSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: ZwavejsSettingsUpdate) => zwavejsService.updateSettings(changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.zwavejs.settings })
      await queryClient.invalidateQueries({ queryKey: queryKeys.zwavejs.status })
    },
  })
}

export function useTestZwavejsConnectionMutation() {
  return useMutation({
    mutationFn: (payload: ZwavejsTestConnectionRequest) => zwavejsService.testConnection(payload),
  })
}

export function useSyncZwavejsEntitiesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const data = await zwavejsService.syncEntities()
      return { data, notice: formatEntitiesSyncNotice(data) }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.entities.all })
    },
  })
}
