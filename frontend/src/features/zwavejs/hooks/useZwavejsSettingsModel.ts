import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { shallowEqual, splitMaskedFlags } from '@/features/settings/hooks/settingsUtils'
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
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy = settingsQuery.isLoading || syncEntities.isPending || updateSettings.isPending

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
      setNotice('Saved Z-Wave JS settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Z-Wave JS settings.')
    }
  }

  const saveDisabled = !draft || !initialDraft || shallowEqual(draft, initialDraft)

  const sync = async () => {
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to sync entities.')
      return
    }
    try {
      const res = await syncEntities.mutateAsync()
      setNotice(res.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Entity sync failed')
    }
  }

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
    refresh,
    save,
    saveDisabled,
    sync,
  }
}
