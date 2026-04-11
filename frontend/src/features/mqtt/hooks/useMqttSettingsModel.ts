import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { shallowEqual, splitMaskedFlags } from '@/features/settings/hooks/settingsUtils'
import { useFrigateSettingsQuery } from '@/hooks/useFrigate'
import {
  useMqttSettingsQuery,
  useMqttStatusQuery,
  useUpdateMqttSettingsMutation,
} from '@/hooks/useMqtt'
import { useZigbee2mqttSettingsQuery } from '@/hooks/useZigbee2mqtt'
import {
  useHomeAssistantMqttAlarmEntitySettingsQuery,
} from '@/hooks/useHomeAssistantMqttAlarmEntity'

export function useMqttSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useMqttStatusQuery()
  const settingsQuery = useMqttSettingsQuery()
  const updateSettings = useUpdateMqttSettingsMutation()
  const zigbee2mqttSettingsQuery = useZigbee2mqttSettingsQuery()
  const frigateSettingsQuery = useFrigateSettingsQuery()
  useHomeAssistantMqttAlarmEntitySettingsQuery()

  const { values: initialDraft, maskedFlags } = useMemo(
    () => splitMaskedFlags(settingsQuery.data),
    [settingsQuery.data]
  )

  const { draft, setDraft } = useDraftFromQuery<Record<string, unknown>>(initialDraft)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy = settingsQuery.isLoading || updateSettings.isPending

  const handleFieldChange = (key: string, value: unknown) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const refresh = () => {
    void statusQuery.refetch()
    void settingsQuery.refetch()
  }

  const save = async () => {
    if (!draft) return
    setError(null)
    setNotice(null)
    try {
      await updateSettings.mutateAsync(draft)
      setNotice('Saved MQTT settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save MQTT settings.')
    }
  }

  const saveDisabled = !draft || !initialDraft || shallowEqual(draft, initialDraft)

  return {
    isAdmin,
    draft,
    maskedFlags,
    handleFieldChange,
    isBusy,
    error,
    notice,
    statusQuery,
    settingsQuery,
    zigbee2mqttSettingsQuery,
    frigateSettingsQuery,
    refresh,
    save,
    saveDisabled,
  }
}
