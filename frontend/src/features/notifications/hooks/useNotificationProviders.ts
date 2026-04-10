/**
 * React Query hooks for notification providers (read-only)
 * Providers are now configured via environment variables (ADR-0075)
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsService } from '@/services/notifications'

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

export function useTestNotificationProvider() {
  return useMutation({
    mutationFn: (id: string) => notificationsService.testProvider(id),
  })
}

export function useToggleNotificationProviderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, isEnabled }: { id: string; isEnabled: boolean }) =>
      notificationsService.toggleProvider(id, isEnabled),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    },
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
