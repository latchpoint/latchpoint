import { useMemo } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { shallowEqual, splitMaskedFlags } from '@/features/settings/hooks/settingsUtils'
import { useSettingsActionFeedback } from '@/features/integrations/lib/settingsFeedback'
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

  const feedback = useSettingsActionFeedback()

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
    await feedback.runSave(
      () => updateHaSettings.mutateAsync(connectionDraft),
      'Saved Home Assistant settings.'
    )
  }

  const connectionSaveDisabled = !connectionDraft || !initialDraft || shallowEqual(connectionDraft, initialDraft)

  const refreshConnection = () =>
    feedback.runRefresh(async () => {
      await Promise.all([haStatusQuery.refetch(), haSettingsQuery.refetch()])
    }, 'Refreshed Home Assistant settings.')

  const refreshMqttEntity = () =>
    feedback.runRefresh(async () => {
      await Promise.all([haMqttAlarmEntityQuery.refetch(), haMqttAlarmEntityStatusQuery.refetch()])
    }, 'Refreshed Home Assistant MQTT alarm entity.')

  const saveMqttEntity = async () => {
    if (!haMqttEntityDraft) return
    await feedback.runSave(
      () =>
        updateHaMqttAlarmEntityMutation.mutateAsync({
          enabled: haMqttEntityDraft.enabled,
          entityName: haMqttEntityDraft.entityName.trim(),
          haEntityId: haMqttEntityDraft.haEntityId.trim(),
          alsoRenameInHomeAssistant: haMqttEntityDraft.alsoRenameInHomeAssistant,
        }),
      'Saved Home Assistant MQTT alarm entity settings.'
    )
  }

  const publishDiscovery = async () => {
    try {
      await publishHaMqttDiscoveryMutation.mutateAsync()
      feedback.setNotice('Published Home Assistant discovery config.')
    } catch (err) {
      feedback.setError(getErrorMessage(err) || 'Failed to publish discovery config')
    }
  }

  return {
    isAdmin,
    error: feedback.error,
    notice: feedback.notice,
    noticeVariant: feedback.noticeVariant,
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
