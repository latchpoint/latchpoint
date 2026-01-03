import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { parseFloatInRange } from '@/lib/numberParsers'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { useMqttSettingsQuery, useMqttStatusQuery } from '@/hooks/useMqtt'
import { useHomeAssistantSettingsQuery, useHomeAssistantStatus, useUpdateHomeAssistantSettingsMutation } from '@/hooks/useHomeAssistant'
import {
  useHomeAssistantMqttAlarmEntitySettingsQuery,
  useHomeAssistantMqttAlarmEntityStatusQuery,
  usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation,
  useUpdateHomeAssistantMqttAlarmEntitySettingsMutation,
} from '@/hooks/useHomeAssistantMqttAlarmEntity'

export type HaConnectionDraft = {
  enabled: boolean
  baseUrl: string
  connectTimeoutSeconds: string
  hasToken: boolean
  token: string
  tokenTouched: boolean
}

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
  const updateHaSettingsMutation = useUpdateHomeAssistantSettingsMutation()

  const mqttStatusQuery = useMqttStatusQuery()
  const mqttSettingsQuery = useMqttSettingsQuery()
  const haMqttAlarmEntityQuery = useHomeAssistantMqttAlarmEntitySettingsQuery()
  const haMqttAlarmEntityStatusQuery = useHomeAssistantMqttAlarmEntityStatusQuery()
  const updateHaMqttAlarmEntityMutation = useUpdateHomeAssistantMqttAlarmEntitySettingsMutation()
  const publishHaMqttDiscoveryMutation = usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation()

  const mqttReady = Boolean(mqttStatusQuery.data?.enabled && mqttSettingsQuery.data?.host)
  const haMqttEntityStatus = haMqttAlarmEntityStatusQuery.data?.status ?? null

  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const initialHaConnectionDraft = useMemo<HaConnectionDraft | null>(() => {
    const s = haSettingsQuery.data
    if (!s) return null
    return {
      enabled: Boolean(s.enabled),
      baseUrl: s.baseUrl ?? '',
      connectTimeoutSeconds: String(s.connectTimeoutSeconds ?? 2),
      hasToken: Boolean(s.hasToken),
      token: '',
      tokenTouched: false,
    }
  }, [haSettingsQuery.data])

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

  const { draft: haConnectionDraft, setDraft: setHaConnectionDraft } = useDraftFromQuery<HaConnectionDraft>(initialHaConnectionDraft)
  const { draft: haMqttEntityDraft, setDraft: setHaMqttEntityDraft } = useDraftFromQuery<HaMqttEntityDraft>(initialHaMqttEntityDraft)

  const refreshConnection = () => {
    void haStatusQuery.refetch()
    void haSettingsQuery.refetch()
  }

  const clearToken = async () => {
    setError(null)
    setNotice(null)
    if (!isAdmin) return
    try {
      await updateHaSettingsMutation.mutateAsync({ enabled: false, token: '' })
      setHaConnectionDraft((prev) =>
        prev
          ? {
              ...prev,
              enabled: false,
              hasToken: false,
              token: '',
              tokenTouched: false,
            }
          : prev
      )
      setNotice('Cleared Home Assistant token (Home Assistant disabled).')
      refreshConnection()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to clear Home Assistant token')
    }
  }

  const resetConnection = () => {
    if (!isAdmin || updateHaSettingsMutation.isPending) return
    const ok = window.confirm(
      'Reset Home Assistant settings?\n\nThis will disable Home Assistant, clear the token, and reset the connection settings to defaults.'
    )
    if (!ok) return
    void (async () => {
      setError(null)
      setNotice(null)
      try {
        await updateHaSettingsMutation.mutateAsync({
          enabled: false,
          baseUrl: 'http://localhost:8123',
          token: '',
          connectTimeoutSeconds: 2,
        })
        await haStatusQuery.refetch()
        await haSettingsQuery.refetch()
        setHaConnectionDraft((prev) =>
          prev
            ? {
                ...prev,
                enabled: false,
                baseUrl: 'http://localhost:8123',
                connectTimeoutSeconds: '2',
                hasToken: false,
                token: '',
                tokenTouched: false,
              }
            : prev
        )
        setNotice('Reset Home Assistant settings.')
      } catch (err) {
        setError(getErrorMessage(err) || 'Failed to reset Home Assistant settings')
      }
    })()
  }

  const saveConnection = async () => {
    if (!haConnectionDraft) return
    setError(null)
    setNotice(null)
    if (!isAdmin) return

    try {
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', haConnectionDraft.connectTimeoutSeconds, 0.5, 30)
      await updateHaSettingsMutation.mutateAsync({
        enabled: haConnectionDraft.enabled,
        baseUrl: haConnectionDraft.baseUrl.trim(),
        connectTimeoutSeconds,
        ...(haConnectionDraft.tokenTouched ? { token: haConnectionDraft.token } : {}),
      })
      setNotice('Saved Home Assistant connection settings.')
      setHaConnectionDraft((prev) => (prev ? { ...prev, token: '', tokenTouched: false } : prev))
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Home Assistant connection settings')
    }
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
    haConnectionDraft,
    setHaConnectionDraft,
    haMqttEntityDraft,
    setHaMqttEntityDraft,
    updateHaSettingsMutation,
    clearToken,
    refreshConnection,
    resetConnection,
    saveConnection,
    updateHaMqttAlarmEntityMutation,
    publishHaMqttDiscoveryMutation,
    refreshMqttEntity,
    saveMqttEntity,
    publishDiscovery,
  }
}

