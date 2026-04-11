import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
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

  const maskedFlags = useMemo<Record<string, boolean>>(() => {
    const s = settingsQuery.data
    if (!s) return {}
    const flags: Record<string, boolean> = {}
    for (const [key, value] of Object.entries(s)) {
      if (key.startsWith('has') && typeof value === 'boolean') {
        flags[key] = value
      }
    }
    return flags
  }, [settingsQuery.data])

  const initialDraft = useMemo<Record<string, unknown> | null>(() => {
    const s = settingsQuery.data
    if (!s) return null
    const values: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(s)) {
      if (!key.startsWith('has')) {
        values[key] = value
      }
    }
    return values
  }, [settingsQuery.data])

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

  const saveDisabled = !draft || !initialDraft || (
    JSON.stringify(draft) === JSON.stringify(initialDraft)
  )

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
