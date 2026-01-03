import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import {
  useSyncZigbee2mqttDevicesMutation,
  useUpdateZigbee2mqttSettingsMutation,
  useZigbee2mqttDevicesQuery,
  useZigbee2mqttSettingsQuery,
  useZigbee2mqttStatusQuery,
} from '@/hooks/useZigbee2mqtt'

export type Zigbee2mqttDraft = {
  enabled: boolean
  baseTopic: string
  runRulesOnEvent: boolean
  runRulesDebounceSeconds: string
  runRulesMaxPerMinute: string
  runRulesKindsCsv: string
}

const DEFAULT_DRAFT: Zigbee2mqttDraft = {
  enabled: false,
  baseTopic: 'zigbee2mqtt',
  runRulesOnEvent: false,
  runRulesDebounceSeconds: '2',
  runRulesMaxPerMinute: '30',
  runRulesKindsCsv: 'trigger',
}

export function useZigbee2mqttSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useZigbee2mqttStatusQuery()
  const settingsQuery = useZigbee2mqttSettingsQuery()
  const devicesQuery = useZigbee2mqttDevicesQuery()

  const updateSettings = useUpdateZigbee2mqttSettingsMutation()
  const syncDevices = useSyncZigbee2mqttDevicesMutation()

  const initialDraft = useMemo<Zigbee2mqttDraft | null>(() => {
    const s = settingsQuery.data
    if (!s) return null
    return {
      enabled: Boolean(s.enabled),
      baseTopic: s.baseTopic || DEFAULT_DRAFT.baseTopic,
      runRulesOnEvent: Boolean(s.runRulesOnEvent ?? false),
      runRulesDebounceSeconds: String(s.runRulesDebounceSeconds ?? 2),
      runRulesMaxPerMinute: String(s.runRulesMaxPerMinute ?? 30),
      runRulesKindsCsv: (s.runRulesKinds ?? ['trigger']).join(', '),
    }
  }, [settingsQuery.data])

  const [draftOverride, setDraftOverride] = useState<Zigbee2mqttDraft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const draft = draftOverride ?? initialDraft
  const ensureDraft = (prev: Zigbee2mqttDraft | null | undefined) => prev ?? draft ?? initialDraft ?? DEFAULT_DRAFT

  const updateDraft = (patch: Partial<Zigbee2mqttDraft>) => {
    setDraftOverride((prev) => ({ ...ensureDraft(prev), ...patch }))
  }

  const isBusy =
    settingsQuery.isLoading ||
    statusQuery.isLoading ||
    updateSettings.isPending ||
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

  const reset = () => {
    if (!isAdmin || isBusy) return
    const ok = window.confirm('Reset Zigbee2MQTT settings?\n\nThis will disable Zigbee2MQTT and reset base topic to default.')
    if (!ok) return
    void (async () => {
      setError(null)
      setNotice(null)
      try {
        await updateSettings.mutateAsync({ enabled: false, baseTopic: DEFAULT_DRAFT.baseTopic })
        await settingsQuery.refetch()
        await statusQuery.refetch()
        setDraftOverride(null)
        setNotice('Reset Zigbee2MQTT settings.')
      } catch (err) {
        setError(getErrorMessage(err) || 'Failed to reset Zigbee2MQTT settings')
      }
    })()
  }

  const save = async () => {
    if (!isAdmin || !draft || isBusy) return
    setError(null)
    setNotice(null)
    try {
      await updateSettings.mutateAsync({
        enabled: draft.enabled,
        baseTopic: (draft.baseTopic || '').trim() || DEFAULT_DRAFT.baseTopic,
        runRulesOnEvent: draft.runRulesOnEvent,
        runRulesDebounceSeconds: Number.parseInt(draft.runRulesDebounceSeconds || '2', 10) || 0,
        runRulesMaxPerMinute: Number.parseInt(draft.runRulesMaxPerMinute || '30', 10) || 0,
        runRulesKinds: draft.runRulesKindsCsv
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      })
      await settingsQuery.refetch()
      await statusQuery.refetch()
      setDraftOverride(null)
      setNotice('Saved Zigbee2MQTT settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Zigbee2MQTT settings')
    }
  }

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
    draft,
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
    updateDraft,
    save,
    reset,
    runSync,
    refresh,
    settingsQuery,
    devicesQuery,
  }
}
