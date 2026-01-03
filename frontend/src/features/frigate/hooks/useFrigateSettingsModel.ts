import { useMemo, useState } from 'react'
import { UserRole } from '@/lib/constants'
import { parseIntInRange } from '@/lib/numberParsers'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { useFrigateDetectionsQuery, useFrigateSettingsQuery, useFrigateStatusQuery, useUpdateFrigateSettingsMutation } from '@/hooks/useFrigate'

export type FrigateDraft = {
  enabled: boolean
  eventsTopic: string
  retentionSeconds: string
  runRulesOnEvent: boolean
  runRulesDebounceSeconds: string
  runRulesMaxPerMinute: string
  runRulesKindsCsv: string
  knownCamerasCsv: string
  knownZonesByCameraJson: string
}

export function useFrigateSettingsModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const statusQuery = useFrigateStatusQuery()
  const settingsQuery = useFrigateSettingsQuery()
  const updateSettings = useUpdateFrigateSettingsMutation()
  const detectionsQuery = useFrigateDetectionsQuery(25)

  const initialDraft = useMemo<FrigateDraft | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      eventsTopic: settingsQuery.data.eventsTopic || 'frigate/events',
      retentionSeconds: String(settingsQuery.data.retentionSeconds ?? 3600),
      runRulesOnEvent: settingsQuery.data.runRulesOnEvent ?? true,
      runRulesDebounceSeconds: String(settingsQuery.data.runRulesDebounceSeconds ?? 2),
      runRulesMaxPerMinute: String(settingsQuery.data.runRulesMaxPerMinute ?? 30),
      runRulesKindsCsv: (settingsQuery.data.runRulesKinds ?? ['trigger']).join(', '),
      knownCamerasCsv: (settingsQuery.data.knownCameras ?? []).join(', '),
      knownZonesByCameraJson: JSON.stringify(settingsQuery.data.knownZonesByCamera ?? {}, null, 0),
    }
  }, [settingsQuery.data])

  const { draft, setDraft } = useDraftFromQuery<FrigateDraft>(initialDraft)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const isBusy = settingsQuery.isLoading || updateSettings.isPending

  const reset = () => {
    if (!isAdmin || isBusy) return
    const ok = window.confirm('Reset Frigate settings?\n\nThis will disable Frigate and reset its MQTT topic and retention settings to defaults.')
    if (!ok) return
    void (async () => {
      setError(null)
      setNotice(null)
      try {
        await updateSettings.mutateAsync({
          enabled: false,
          eventsTopic: 'frigate/events',
          retentionSeconds: 3600,
          runRulesOnEvent: true,
          runRulesDebounceSeconds: 2,
          runRulesMaxPerMinute: 30,
          runRulesKinds: ['trigger'],
          knownCameras: [],
          knownZonesByCamera: {},
        })
        await settingsQuery.refetch()
        await statusQuery.refetch()
        setDraft((prev) =>
          prev
            ? {
                ...prev,
                enabled: false,
                eventsTopic: 'frigate/events',
                retentionSeconds: '3600',
                runRulesOnEvent: true,
                runRulesDebounceSeconds: '2',
                runRulesMaxPerMinute: '30',
                runRulesKindsCsv: 'trigger',
                knownCamerasCsv: '',
                knownZonesByCameraJson: '{}',
              }
            : prev
        )
        setNotice('Reset Frigate settings.')
      } catch (err) {
        setError(getErrorMessage(err) || 'Failed to reset Frigate settings.')
      }
    })()
  }

  const save = async () => {
    if (!isAdmin || !draft || isBusy) return
    setError(null)
    setNotice(null)
    try {
      const retentionSeconds = parseIntInRange('Retention seconds', draft.retentionSeconds, 60, 60 * 60 * 24 * 7)
      const runRulesDebounceSeconds = parseIntInRange('Rules debounce seconds', draft.runRulesDebounceSeconds, 0, 60)
      const runRulesMaxPerMinute = parseIntInRange('Rules max per minute', draft.runRulesMaxPerMinute, 0, 600)
      const runRulesKinds = draft.runRulesKindsCsv
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const knownCameras = draft.knownCamerasCsv
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const knownZonesByCamera = (() => {
        try {
          const parsed = JSON.parse(draft.knownZonesByCameraJson || '{}')
          return parsed && typeof parsed === 'object' ? (parsed as Record<string, string[]>) : {}
        } catch {
          return {}
        }
      })()
      await updateSettings.mutateAsync({
        enabled: draft.enabled,
        eventsTopic: draft.eventsTopic.trim() || 'frigate/events',
        retentionSeconds,
        runRulesOnEvent: draft.runRulesOnEvent,
        runRulesDebounceSeconds,
        runRulesMaxPerMinute,
        runRulesKinds,
        knownCameras,
        knownZonesByCamera,
      })
      await statusQuery.refetch()
      setNotice('Saved Frigate settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Frigate settings.')
    }
  }

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
    draft,
    setDraft,
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
    save,
    reset,
    refresh,
  }
}
