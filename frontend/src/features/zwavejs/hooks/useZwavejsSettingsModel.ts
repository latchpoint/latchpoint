import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import {
  useSyncZwavejsEntitiesMutation,
  useZwavejsSettingsQuery,
  useZwavejsStatusQuery,
} from '@/hooks/useZwavejs'

export type ZwavejsDraft = {
  enabled: boolean
  wsUrl: string
  connectTimeoutSeconds: string
  reconnectMinSeconds: string
  reconnectMaxSeconds: string
}

export function useZwavejsSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useZwavejsStatusQuery()
  const settingsQuery = useZwavejsSettingsQuery()
  const syncEntities = useSyncZwavejsEntitiesMutation()

  const initialDraft = useMemo<ZwavejsDraft | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      wsUrl: settingsQuery.data.wsUrl || '',
      connectTimeoutSeconds: String(settingsQuery.data.connectTimeoutSeconds ?? 5),
      reconnectMinSeconds: String(settingsQuery.data.reconnectMinSeconds ?? 1),
      reconnectMaxSeconds: String(settingsQuery.data.reconnectMaxSeconds ?? 30),
    }
  }, [settingsQuery.data])

  const { draft, setDraft } = useDraftFromQuery<ZwavejsDraft>(initialDraft)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy = settingsQuery.isLoading || syncEntities.isPending

  const refresh = () => {
    void statusQuery.refetch()
    void settingsQuery.refetch()
  }

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
    initialDraft,
    isBusy,
    error,
    notice,
    statusQuery,
    settingsQuery,
    refresh,
    sync,
  }
}
