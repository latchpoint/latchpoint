import { useState } from 'react'
import { UserRole } from '@/lib/constants'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useFrigateDetectionsQuery, useFrigateSettingsQuery, useFrigateStatusQuery } from '@/hooks/useFrigate'

export function useFrigateSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useFrigateStatusQuery()
  const settingsQuery = useFrigateSettingsQuery()
  const detectionsQuery = useFrigateDetectionsQuery(25)

  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy = settingsQuery.isLoading

  const status = statusQuery.data
  const mqttConnected = status?.mqtt?.connected ?? false
  const mqttEnabled = status?.mqtt?.enabled ?? false
  const mqttConfigured = status?.mqtt?.configured ?? false
  const mqttReady = mqttEnabled && mqttConfigured

  const refresh = () => {
    setError(null)
    setNotice(null)
    void statusQuery.refetch()
    void settingsQuery.refetch()
    void detectionsQuery.refetch()
  }

  return {
    isAdmin,
    settings: settingsQuery.data ?? null,
    error,
    notice,
    setError,
    setNotice,
    isBusy,
    mqttReady,
    mqttConnected,
    statusQuery,
    settingsQuery,
    detectionsQuery,
    refresh,
  }
}
