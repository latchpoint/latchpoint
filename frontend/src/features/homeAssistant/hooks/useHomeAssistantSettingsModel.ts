import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { shallowEqual, splitMaskedFlags } from '@/features/settings/hooks/settingsUtils'
import { useMqttSettingsQuery, useMqttStatusQuery } from '@/hooks/useMqtt'
import { useHomeAssistantSettingsQuery, useHomeAssistantStatus, useUpdateHomeAssistantSettingsMutation } from '@/hooks/useHomeAssistant'
import {
  useHomeAssistantMqttAlarmEntitySettingsQuery,
  useHomeAssistantMqttAlarmEntityStatusQuery,
  usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation,
  useUpdateHomeAssistantMqttAlarmEntitySettingsMutation,
} from '@/hooks/useHomeAssistantMqttAlarmEntity'
import { getErrorMessage } from '@/types/errors'

export type HaMqttEntityDraft = {
  enabled: boolean
  entityName: string
  alsoRenameInHomeAssistant: boolean
  haEntityId: string
}

export function useHomeAssistantSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const haStatusQuery = useHomeAssistantStatus()
  const haSettingsQuery = useHomeAssistantSettingsQuery()

  const mqttStatusQuery = useMqttStatusQuery()
  const mqttSettingsQuery = useMqttSettingsQuery()
  const haMqttAlarmEntityQuery = useHomeAssistantMqttAlarmEntitySettingsQuery()
  const haMqttAlarmEntityStatusQuery = useHomeAssistantMqttAlarmEntityStatusQuery()
  const updateHaMqttAlarmEntityMutation = useUpdateHomeAssistantMqttAlarmEntitySettingsMutation()
  const publishHaMqttDiscoveryMutation = usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation()
  const updateHaSettings = useUpdateHomeAssistantSettingsMutation()

  const mqttReady = Boolean(mqttStatusQuery.data?.enabled && mqttSettingsQuery.data?.host)
  const haMqttEntityStatus = haMqttAlarmEntityStatusQuery.data?.status ?? null

  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const { values: initialDraft, maskedFlags } = useMemo(
    () => splitMaskedFlags(haSettingsQuery.data),
    [haSettingsQuery.data]
  )

  const initialHaMqttEntityDraft = useMemo<HaMqttEntityDraft | null>(() => {
    const s = haMqttAlarmEntityQuery.data
    if (!s) return null
    return {
      enabled: Boolean(s.enabled),
      entityName: s.entityName ?? 'Latchpoint',
      alsoRenameInHomeAssistant: Boolean(s.alsoRenameInHomeAssistant ?? true),
      haEntityId: s.haEntityId ?? 'alarm_control_panel.latchpoint_alarm',
    }
  }, [haMqttAlarmEntityQuery.data])

  const { draft: connectionDraft, setDraft: setConnectionDraft } = useDraftFromQuery<Record<string, unknown>>(initialDraft)
  const { draft: haMqttEntityDraft, setDraft: setHaMqttEntityDraft } = useDraftFromQuery<HaMqttEntityDraft>(initialHaMqttEntityDraft)

  const handleFieldChange = (key: string, value: unknown) => {
    setConnectionDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const saveConnection = async () => {
    if (!connectionDraft) return
    setError(null)
    setNotice(null)
    try {
      await updateHaSettings.mutateAsync(connectionDraft)
      setNotice('Saved Home Assistant settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Home Assistant settings.')
    }
  }

  const connectionSaveDisabled = !connectionDraft || !initialDraft || shallowEqual(connectionDraft, initialDraft)

  const refreshConnection = () => {
    void haStatusQuery.refetch()
    void haSettingsQuery.refetch()
  }

  const refreshMqttEntity = () => {
    void haMqttAlarmEntityQuery.refetch()
    void haMqttAlarmEntityStatusQuery.refetch()
  }

  const saveMqttEntity = async () => {
    if (!haMqttEntityDraft) return
    setError(null)
    setNotice(null)
    try {
      await updateHaMqttAlarmEntityMutation.mutateAsync({
        enabled: haMqttEntityDraft.enabled,
        entityName: haMqttEntityDraft.entityName.trim(),
        haEntityId: haMqttEntityDraft.haEntityId.trim(),
        alsoRenameInHomeAssistant: haMqttEntityDraft.alsoRenameInHomeAssistant,
      })
      setNotice('Saved Home Assistant MQTT alarm entity settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Home Assistant MQTT alarm entity settings')
    }
  }

  const publishDiscovery = async () => {
    setError(null)
    setNotice(null)
    try {
      await publishHaMqttDiscoveryMutation.mutateAsync()
      setNotice('Published Home Assistant discovery config.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to publish discovery config')
    }
  }

  return {
    isAdmin,
    error,
    notice,
    mqttReady,
    haMqttEntityStatus,
    haStatusQuery,
    haSettingsQuery,
    connectionDraft,
    maskedFlags,
    handleFieldChange,
    haMqttEntityDraft,
    setHaMqttEntityDraft,
    updateHaMqttAlarmEntityMutation,
    publishHaMqttDiscoveryMutation,
    saveConnection,
    connectionSaveDisabled,
    isConnectionSaving: updateHaSettings.isPending,
    refreshConnection,
    refreshMqttEntity,
    saveMqttEntity,
    publishDiscovery,
  }
}
