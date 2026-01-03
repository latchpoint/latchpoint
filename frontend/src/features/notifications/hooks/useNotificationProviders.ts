/**
 * React Query hooks for notification providers
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsService } from '@/services/notifications'
import type {
  NotificationProviderCreate,
  NotificationProviderUpdate,
} from '@/types/notifications'

export const notificationKeys = {
  all: ['notification-providers'] as const,
  provider: (id: string) => ['notification-providers', id] as const,
  types: ['notification-provider-types'] as const,
}

export function useNotificationProviders() {
  return useQuery({
    queryKey: notificationKeys.all,
    queryFn: () => notificationsService.listProviders(),
  })
}

export function useNotificationProvider(id: string) {
  return useQuery({
    queryKey: notificationKeys.provider(id),
    queryFn: () => notificationsService.getProvider(id),
    enabled: Boolean(id),
  })
}

export function useNotificationProviderTypes() {
  return useQuery({
    queryKey: notificationKeys.types,
    queryFn: () => notificationsService.getProviderTypes(),
  })
}

export function useCreateNotificationProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: NotificationProviderCreate) =>
      notificationsService.createProvider(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useUpdateNotificationProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: NotificationProviderUpdate }) =>
      notificationsService.updateProvider(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all })
      queryClient.invalidateQueries({ queryKey: notificationKeys.provider(id) })
    },
  })
}

export function useDeleteNotificationProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => notificationsService.deleteProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useTestNotificationProvider() {
  return useMutation({
    mutationFn: (id: string) => notificationsService.testProvider(id),
  })
}

// Hook for enabled providers (for rule builder dropdown)
export function useEnabledNotificationProviders() {
  const query = useNotificationProviders()
  return {
    ...query,
    data: query.data?.filter((p) => p.isEnabled) ?? [],
  }
}
