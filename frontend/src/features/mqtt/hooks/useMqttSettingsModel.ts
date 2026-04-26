import { useMemo } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { shallowEqual, splitMaskedFlags } from '@/features/settings/hooks/settingsUtils'
import { useSettingsActionFeedback } from '@/features/integrations/lib/settingsFeedback'
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
  const feedback = useSettingsActionFeedback()

  const isBusy = settingsQuery.isLoading || updateSettings.isPending

  const handleFieldChange = (key: string, value: unknown) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const refresh = () =>
    feedback.runRefresh(
      async () => {
        const results = await Promise.all([statusQuery.refetch(), settingsQuery.refetch()])
        for (const r of results) if (r.isError) throw r.error
      },
      'Refreshed MQTT settings.'
    )

  const save = async () => {
    if (!draft) return
    await feedback.runSave(() => updateSettings.mutateAsync(draft), 'Saved MQTT settings.')
  }

  const saveDisabled = !draft || !initialDraft || shallowEqual(draft, initialDraft)

  return {
    isAdmin,
    draft,
    maskedFlags,
    handleFieldChange,
    isBusy,
    error: feedback.error,
    notice: feedback.notice,
    noticeVariant: feedback.noticeVariant,
    statusQuery,
    settingsQuery,
    zigbee2mqttSettingsQuery,
    frigateSettingsQuery,
    refresh,
    save,
    saveDisabled,
  }
}
