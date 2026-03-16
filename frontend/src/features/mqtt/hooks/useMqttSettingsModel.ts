import { useMemo } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { useFrigateSettingsQuery } from '@/hooks/useFrigate'
import {
  useMqttSettingsQuery,
  useMqttStatusQuery,
} from '@/hooks/useMqtt'
import { useZigbee2mqttSettingsQuery } from '@/hooks/useZigbee2mqtt'
import {
  useHomeAssistantMqttAlarmEntitySettingsQuery,
} from '@/hooks/useHomeAssistantMqttAlarmEntity'

export type MqttDraft = {
  enabled: boolean
  host: string
  port: string
  username: string
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
  const zigbee2mqttSettingsQuery = useZigbee2mqttSettingsQuery()
  const frigateSettingsQuery = useFrigateSettingsQuery()
  useHomeAssistantMqttAlarmEntitySettingsQuery()

  const initialDraft = useMemo<MqttDraft | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      host: settingsQuery.data.host || '',
      port: String(settingsQuery.data.port ?? 1883),
      username: settingsQuery.data.username || '',
      useTls: settingsQuery.data.useTls,
      tlsInsecure: settingsQuery.data.tlsInsecure,
      clientId: settingsQuery.data.clientId || 'latchpoint-alarm',
      keepaliveSeconds: String(settingsQuery.data.keepaliveSeconds ?? 30),
      connectTimeoutSeconds: String(settingsQuery.data.connectTimeoutSeconds ?? 5),
      hasPassword: Boolean(settingsQuery.data.hasPassword),
    }
  }, [settingsQuery.data])

  const { draft, setDraft } = useDraftFromQuery<MqttDraft>(initialDraft)

  const isBusy = settingsQuery.isLoading

  const refresh = () => {
    void statusQuery.refetch()
    void settingsQuery.refetch()
  }

  return {
    isAdmin,
    draft,
    setDraft,
    initialDraft,
    isBusy,
    error: null as string | null,
    notice: null as string | null,
    statusQuery,
    settingsQuery,
    zigbee2mqttSettingsQuery,
    frigateSettingsQuery,
    refresh,
  }
}
