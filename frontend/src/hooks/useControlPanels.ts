import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { controlPanelsService } from '@/services'
import { queryKeys } from '@/types'
import type { ControlPanelDeviceCreate, ControlPanelDeviceUpdate } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'

export function useControlPanelsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.controlPanels.all,
    queryFn: controlPanelsService.list,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useCreateControlPanelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ControlPanelDeviceCreate) => controlPanelsService.create(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.controlPanels.all })
    },
  })
}

export function useUpdateControlPanelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: ControlPanelDeviceUpdate }) =>
      controlPanelsService.update(id, changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.controlPanels.all })
    },
  })
}

export function useDeleteControlPanelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => controlPanelsService.delete(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.controlPanels.all })
    },
  })
}

export function useTestControlPanelMutation() {
  return useMutation({
    mutationFn: (id: number) => controlPanelsService.test(id),
  })
}
