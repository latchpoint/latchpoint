import { useMemo } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { shallowEqual, splitMaskedFlags } from '@/features/settings/hooks/settingsUtils'
import { useSettingsActionFeedback } from '@/features/integrations/lib/settingsFeedback'
import {
  useSyncZwavejsEntitiesMutation,
  useUpdateZwavejsSettingsMutation,
  useZwavejsSettingsQuery,
  useZwavejsStatusQuery,
} from '@/hooks/useZwavejs'

export function useZwavejsSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useZwavejsStatusQuery()
  const settingsQuery = useZwavejsSettingsQuery()
  const updateSettings = useUpdateZwavejsSettingsMutation()
  const syncEntities = useSyncZwavejsEntitiesMutation()

  const { values: initialDraft, maskedFlags } = useMemo(
    () => splitMaskedFlags(settingsQuery.data),
    [settingsQuery.data]
  )

  const { draft, setDraft } = useDraftFromQuery<Record<string, unknown>>(initialDraft)
  const feedback = useSettingsActionFeedback()

  const isBusy = settingsQuery.isLoading || syncEntities.isPending || updateSettings.isPending

  const handleFieldChange = (key: string, value: unknown) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const refresh = () =>
    feedback.runRefresh(
      async () => {
        await Promise.all([statusQuery.refetch(), settingsQuery.refetch()])
      },
      'Refreshed Z-Wave JS settings.'
    )

  const save = async () => {
    if (!draft) return
    await feedback.runSave(() => updateSettings.mutateAsync(draft), 'Saved Z-Wave JS settings.')
  }

  const saveDisabled = !draft || !initialDraft || shallowEqual(draft, initialDraft)

  const sync = async () => {
    if (!isAdmin) {
      feedback.setError('Admin role required to sync entities.')
      return
    }
    try {
      const res = await syncEntities.mutateAsync()
      feedback.setNotice(res.notice)
    } catch (err) {
      feedback.setError(getErrorMessage(err) || 'Entity sync failed')
    }
  }

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
    refresh,
    save,
    saveDisabled,
    sync,
  }
}
