import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { frigateService } from '@/services'
import { queryKeys } from '@/types'
import type { FrigateSettingsUpdate } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { ONE_MINUTE_MS, UserRole } from '@/lib/constants'

export function useFrigateStatusQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.frigate.status,
    queryFn: frigateService.getStatus,
    enabled: isAuthenticated,
  })
}

export function useFrigateSettingsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.frigate.settings,
    queryFn: frigateService.getSettings,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useUpdateFrigateSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: FrigateSettingsUpdate) => frigateService.updateSettings(changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.frigate.settings })
      await queryClient.invalidateQueries({ queryKey: queryKeys.frigate.status })
    },
  })
}

export function useFrigateOptionsQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.frigate.options,
    queryFn: frigateService.getOptions,
    enabled: isAuthenticated,
    staleTime: ONE_MINUTE_MS,
  })
}

export function useFrigateDetectionsQuery(limit: number = 20) {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: [...queryKeys.frigate.detections, limit],
    queryFn: () => frigateService.listDetections({ limit }),
    enabled: isAuthenticated && isAdmin,
  })
}
