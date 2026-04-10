import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { parseIntInRange } from '@/lib/numberParsers'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import {
  useSyncZwavejsEntitiesMutation,
  useUpdateZwavejsSettingsMutation,
  useZwavejsSettingsQuery,
  useZwavejsStatusQuery,
} from '@/hooks/useZwavejs'

export type ZwavejsDraft = {
  enabled: boolean
  wsUrl: string
  hasApiToken: boolean
  connectTimeoutSeconds: string
  reconnectMinSeconds: string
  reconnectMaxSeconds: string
}

export function useZwavejsSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useZwavejsStatusQuery()
  const settingsQuery = useZwavejsSettingsQuery()
  const updateSettings = useUpdateZwavejsSettingsMutation()
  const syncEntities = useSyncZwavejsEntitiesMutation()

  const initialDraft = useMemo<ZwavejsDraft | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      wsUrl: settingsQuery.data.wsUrl || '',
      hasApiToken: Boolean(settingsQuery.data.hasApiToken),
      connectTimeoutSeconds: String(settingsQuery.data.connectTimeoutSeconds ?? 5),
      reconnectMinSeconds: String(settingsQuery.data.reconnectMinSeconds ?? 1),
      reconnectMaxSeconds: String(settingsQuery.data.reconnectMaxSeconds ?? 30),
    }
  }, [settingsQuery.data])

  const { draft, setDraft } = useDraftFromQuery<ZwavejsDraft>(initialDraft)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy = settingsQuery.isLoading || syncEntities.isPending || updateSettings.isPending

  const refresh = () => {
    void statusQuery.refetch()
    void settingsQuery.refetch()
  }

  const save = async () => {
    if (!draft) return
    setError(null)
    setNotice(null)
    try {
      const connectTimeoutSeconds = parseIntInRange('Connect timeout', draft.connectTimeoutSeconds, 1, 300)
      const reconnectMinSeconds = parseIntInRange('Reconnect min', draft.reconnectMinSeconds, 1, 300)
      const reconnectMaxSeconds = parseIntInRange('Reconnect max', draft.reconnectMaxSeconds, 1, 3600)
      await updateSettings.mutateAsync({ connectTimeoutSeconds, reconnectMinSeconds, reconnectMaxSeconds })
      setNotice('Saved Z-Wave JS settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Z-Wave JS settings.')
    }
  }

  const saveDisabled = !draft || !initialDraft || (
    draft.connectTimeoutSeconds === initialDraft.connectTimeoutSeconds &&
    draft.reconnectMinSeconds === initialDraft.reconnectMinSeconds &&
    draft.reconnectMaxSeconds === initialDraft.reconnectMaxSeconds
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
    setDraft,
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
