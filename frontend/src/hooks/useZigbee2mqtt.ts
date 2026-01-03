import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { zigbee2mqttService } from '@/services'
import { queryKeys } from '@/types'
import type { Zigbee2mqttSettingsUpdate } from '@/types'
import { useAuthSessionQuery, useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'

export function useZigbee2mqttStatusQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.zigbee2mqtt.status,
    queryFn: zigbee2mqttService.getStatus,
    enabled: isAuthenticated,
  })
}

export function useZigbee2mqttSettingsQuery() {
  const session = useAuthSessionQuery()
  const userQuery = useCurrentUserQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  const isAdmin = userQuery.data?.role === UserRole.ADMIN
  return useQuery({
    queryKey: queryKeys.zigbee2mqtt.settings,
    queryFn: zigbee2mqttService.getSettings,
    enabled: isAuthenticated && isAdmin,
  })
}

export function useUpdateZigbee2mqttSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: Zigbee2mqttSettingsUpdate) => zigbee2mqttService.updateSettings(changes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.zigbee2mqtt.settings })
      await queryClient.invalidateQueries({ queryKey: queryKeys.zigbee2mqtt.status })
    },
  })
}

export function useZigbee2mqttDevicesQuery() {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false
  return useQuery({
    queryKey: queryKeys.zigbee2mqtt.devices,
    queryFn: zigbee2mqttService.listDevices,
    enabled: isAuthenticated,
  })
}

export function useSyncZigbee2mqttDevicesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: zigbee2mqttService.syncDevices,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.zigbee2mqtt.devices })
      await queryClient.invalidateQueries({ queryKey: queryKeys.zigbee2mqtt.status })
      await queryClient.invalidateQueries({ queryKey: queryKeys.entities.all })
    },
  })
}
