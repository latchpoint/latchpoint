import { useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import {
  useSyncZigbee2mqttDevicesMutation,
  useZigbee2mqttDevicesQuery,
  useZigbee2mqttSettingsQuery,
  useZigbee2mqttStatusQuery,
} from '@/hooks/useZigbee2mqtt'

export function useZigbee2mqttSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useZigbee2mqttStatusQuery()
  const settingsQuery = useZigbee2mqttSettingsQuery()
  const devicesQuery = useZigbee2mqttDevicesQuery()
  const syncDevices = useSyncZigbee2mqttDevicesMutation()

  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy =
    settingsQuery.isLoading ||
    statusQuery.isLoading ||
    syncDevices.isPending ||
    devicesQuery.isLoading

  const mqttStatus = statusQuery.data?.mqtt ?? null
  const mqttConnected = mqttStatus?.connected ?? false
  const mqttReady = Boolean(mqttStatus?.enabled && mqttStatus?.configured)
  const z2mEnabled = statusQuery.data?.enabled ?? false
  const z2mConnected = statusQuery.data?.connected ?? false
  const lastSyncAt = statusQuery.data?.sync?.lastSyncAt ?? null
  const lastDeviceCount = statusQuery.data?.sync?.lastDeviceCount ?? null
  const lastSyncError = statusQuery.data?.sync?.lastError ?? null

  const runSync = async () => {
    if (!isAdmin || isBusy) return
    setError(null)
    setNotice(null)
    try {
      const res = await syncDevices.mutateAsync()
      await devicesQuery.refetch()
      setNotice(`Synced Zigbee2MQTT: ${res.devices} device(s), ${res.entitiesUpserted} entity(ies).`)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync Zigbee2MQTT devices')
    }
  }

  const refresh = () => {
    setError(null)
    setNotice(null)
    void settingsQuery.refetch()
    void statusQuery.refetch()
    void devicesQuery.refetch()
  }

  return {
    isAdmin,
    settings: settingsQuery.data ?? null,
    isBusy,
    mqttReady,
    mqttConnected,
    z2mEnabled,
    z2mConnected,
    lastSyncAt,
    lastDeviceCount,
    lastSyncError,
    error,
    notice,
    setError,
    setNotice,
    runSync,
    refresh,
    settingsQuery,
    devicesQuery,
  }
}
