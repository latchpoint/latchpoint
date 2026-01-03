import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { parseFloatInRange, parseIntInRange } from '@/lib/numberParsers'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import {
  useSyncZwavejsEntitiesMutation,
  useTestZwavejsConnectionMutation,
  useUpdateZwavejsSettingsMutation,
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
  const updateSettings = useUpdateZwavejsSettingsMutation()
  const testConnection = useTestZwavejsConnectionMutation()
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

  const isBusy = settingsQuery.isLoading || updateSettings.isPending || testConnection.isPending || syncEntities.isPending

  const refresh = () => {
    void statusQuery.refetch()
    void settingsQuery.refetch()
  }

  const reset = () => {
    if (!isAdmin || isBusy) return
    const ok = window.confirm(
      'Reset Z-Wave JS settings?\n\nThis will disable Z-Wave JS, clear credentials, and reset all Z-Wave JS settings to defaults.'
    )
    if (!ok) return
    void (async () => {
      setError(null)
      setNotice(null)
      try {
        await updateSettings.mutateAsync({
          enabled: false,
          wsUrl: 'ws://localhost:3000',
          apiToken: '',
          connectTimeoutSeconds: 5,
          reconnectMinSeconds: 1,
          reconnectMaxSeconds: 30,
        })
        await settingsQuery.refetch()
        await statusQuery.refetch()
        setDraft((prev) =>
          prev
            ? {
                ...prev,
                enabled: false,
                wsUrl: 'ws://localhost:3000',
                connectTimeoutSeconds: '5',
                reconnectMinSeconds: '1',
                reconnectMaxSeconds: '30',
              }
            : prev
        )
        setNotice('Reset Z-Wave JS settings.')
      } catch (err) {
        setError(getErrorMessage(err) || 'Failed to reset Z-Wave JS settings')
      }
    })()
  }

  const save = async () => {
    if (!draft) return
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure Z-Wave JS.')
      return
    }

    try {
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', draft.connectTimeoutSeconds, 0.5, 30)
      const reconnectMinSeconds = parseIntInRange('Reconnect min', draft.reconnectMinSeconds, 0, 300)
      const reconnectMaxSeconds = parseIntInRange('Reconnect max', draft.reconnectMaxSeconds, 0, 300)
      if (reconnectMaxSeconds && reconnectMinSeconds && reconnectMaxSeconds < reconnectMinSeconds) {
        throw new Error('Reconnect max must be >= reconnect min.')
      }
      if (draft.enabled) {
        const wsUrl = draft.wsUrl.trim()
        if (!wsUrl) throw new Error('WebSocket URL is required when Z-Wave JS is enabled.')
        if (!(wsUrl.startsWith('ws://') || wsUrl.startsWith('wss://'))) throw new Error('WebSocket URL must start with ws:// or wss://.')
      }

      await updateSettings.mutateAsync({
        enabled: draft.enabled,
        wsUrl: draft.wsUrl.trim(),
        connectTimeoutSeconds,
        reconnectMinSeconds,
        reconnectMaxSeconds,
      })
      setNotice('Saved Z-Wave JS settings.')
      void statusQuery.refetch()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Z-Wave JS settings')
    }
  }

  const test = async () => {
    if (!draft) return
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure Z-Wave JS.')
      return
    }

    try {
      const wsUrl = draft.wsUrl.trim()
      if (!wsUrl) throw new Error('WebSocket URL is required.')
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', draft.connectTimeoutSeconds, 0.5, 30)
      await testConnection.mutateAsync({ wsUrl, connectTimeoutSeconds })
      setNotice('Connection OK.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Connection failed')
    }
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
    reset,
    save,
    test,
    sync,
  }
}
