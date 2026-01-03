import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { parseFloatInRange, parseIntInRange } from '@/lib/numberParsers'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { useFrigateSettingsQuery } from '@/hooks/useFrigate'
import {
  useMqttSettingsQuery,
  useMqttStatusQuery,
  useTestMqttConnectionMutation,
  useUpdateMqttSettingsMutation,
} from '@/hooks/useMqtt'
import { useZigbee2mqttSettingsQuery } from '@/hooks/useZigbee2mqtt'
import {
  useHomeAssistantMqttAlarmEntitySettingsQuery,
  useUpdateHomeAssistantMqttAlarmEntitySettingsMutation,
} from '@/hooks/useHomeAssistantMqttAlarmEntity'

export type MqttDraft = {
  enabled: boolean
  host: string
  port: string
  username: string
  password: string
  useTls: boolean
  tlsInsecure: boolean
  clientId: string
  keepaliveSeconds: string
  connectTimeoutSeconds: string
  hasPassword: boolean
}

export function useMqttSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useMqttStatusQuery()
  const settingsQuery = useMqttSettingsQuery()
  const updateSettings = useUpdateMqttSettingsMutation()
  const testConnection = useTestMqttConnectionMutation()
  const zigbee2mqttSettingsQuery = useZigbee2mqttSettingsQuery()
  const frigateSettingsQuery = useFrigateSettingsQuery()
  const haMqttAlarmEntityQuery = useHomeAssistantMqttAlarmEntitySettingsQuery()
  const updateHaMqttAlarmEntityMutation = useUpdateHomeAssistantMqttAlarmEntitySettingsMutation()

  const initialDraft = useMemo<MqttDraft | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      host: settingsQuery.data.host || '',
      port: String(settingsQuery.data.port ?? 1883),
      username: settingsQuery.data.username || '',
      password: '',
      useTls: settingsQuery.data.useTls,
      tlsInsecure: settingsQuery.data.tlsInsecure,
      clientId: settingsQuery.data.clientId || 'latchpoint-alarm',
      keepaliveSeconds: String(settingsQuery.data.keepaliveSeconds ?? 30),
      connectTimeoutSeconds: String(settingsQuery.data.connectTimeoutSeconds ?? 5),
      hasPassword: Boolean(settingsQuery.data.hasPassword),
    }
  }, [settingsQuery.data])

  const { draft, setDraft } = useDraftFromQuery<MqttDraft>(initialDraft)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy =
    settingsQuery.isLoading ||
    updateSettings.isPending ||
    testConnection.isPending ||
    updateHaMqttAlarmEntityMutation.isPending

  const refresh = () => {
    void statusQuery.refetch()
    void settingsQuery.refetch()
  }

  const reset = () => {
    if (!isAdmin || isBusy) return
    const willResetHaMqttEntity = Boolean(haMqttAlarmEntityQuery.data?.enabled)
    const ok = window.confirm(
      [
        'Reset MQTT settings?',
        '',
        'This will disable MQTT, clear credentials, and reset all MQTT settings to defaults.',
        ...(willResetHaMqttEntity
          ? [
              '',
              'Home Assistant MQTT alarm entity is currently enabled.',
              'Resetting MQTT will also reset/disable the Home Assistant MQTT alarm entity.',
            ]
          : []),
      ].join('\n')
    )
    if (!ok) return
    void (async () => {
      setError(null)
      setNotice(null)
      try {
        if (willResetHaMqttEntity) {
          await updateHaMqttAlarmEntityMutation.mutateAsync({
            enabled: false,
            entityName: 'Latchpoint',
            alsoRenameInHomeAssistant: true,
            haEntityId: 'alarm_control_panel.latchpoint_alarm',
          })
          await haMqttAlarmEntityQuery.refetch()
        }

        await updateSettings.mutateAsync({
          enabled: false,
          host: 'localhost',
          port: 1883,
          username: '',
          password: '',
          useTls: false,
          tlsInsecure: false,
          clientId: 'latchpoint-alarm',
          keepaliveSeconds: 30,
          connectTimeoutSeconds: 5,
        })
        await settingsQuery.refetch()
        await statusQuery.refetch()
        setDraft((prev) =>
          prev
            ? {
                ...prev,
                enabled: false,
                host: 'localhost',
                port: '1883',
                username: '',
                password: '',
                useTls: false,
                tlsInsecure: false,
                clientId: 'latchpoint-alarm',
                keepaliveSeconds: '30',
                connectTimeoutSeconds: '5',
                hasPassword: false,
              }
            : prev
        )
        setNotice('Reset MQTT settings.')
      } catch (err) {
        setError(getErrorMessage(err) || 'Failed to reset MQTT settings')
      }
    })()
  }

  const save = async () => {
    if (!draft) return
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure MQTT.')
      return
    }

    try {
      const port = parseIntInRange('Port', draft.port, 1, 65535)
      const keepaliveSeconds = parseIntInRange('Keepalive', draft.keepaliveSeconds, 5, 3600)
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', draft.connectTimeoutSeconds, 0.5, 30)
      const host = draft.host.trim()
      if (draft.enabled && !host) throw new Error('Broker host is required when MQTT is enabled.')

      await updateSettings.mutateAsync({
        enabled: draft.enabled,
        host,
        port,
        username: draft.username.trim(),
        ...(draft.password.trim() ? { password: draft.password } : {}),
        useTls: draft.useTls,
        tlsInsecure: draft.tlsInsecure,
        clientId: draft.clientId.trim() || 'latchpoint-alarm',
        keepaliveSeconds,
        connectTimeoutSeconds,
      })

      setDraft((prev) => (prev ? { ...prev, password: '' } : prev))
      setNotice('Saved MQTT settings.')
      void statusQuery.refetch()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save MQTT settings')
    }
  }

  const test = async () => {
    if (!draft) return
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure MQTT.')
      return
    }

    try {
      const port = parseIntInRange('Port', draft.port, 1, 65535)
      const keepaliveSeconds = parseIntInRange('Keepalive', draft.keepaliveSeconds, 5, 3600)
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', draft.connectTimeoutSeconds, 0.5, 30)
      const host = draft.host.trim()
      if (!host) throw new Error('Broker host is required.')

      await testConnection.mutateAsync({
        host,
        port,
        username: draft.username.trim() || undefined,
        password: draft.password.trim() || undefined,
        useTls: draft.useTls,
        tlsInsecure: draft.tlsInsecure,
        clientId: draft.clientId.trim() || 'latchpoint-alarm',
        keepaliveSeconds,
        connectTimeoutSeconds,
      })
      setNotice('Connection OK.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Connection failed')
    }
  }

  const clearPassword = async () => {
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure MQTT.')
      return
    }
    try {
      await updateSettings.mutateAsync({ password: '' })
      setDraft((prev) => (prev ? { ...prev, password: '', hasPassword: false } : prev))
      setNotice('Cleared MQTT password.')
      void statusQuery.refetch()
      void settingsQuery.refetch()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to clear MQTT password')
    }
  }

  return {
    isAdmin,
    draft,
    setDraft,
    initialDraft,
    isBusy,
    error,
    notice,
    statusQuery,
    settingsQuery,
    zigbee2mqttSettingsQuery,
    frigateSettingsQuery,
    refresh,
    reset,
    save,
    test,
    clearPassword,
  }
}

