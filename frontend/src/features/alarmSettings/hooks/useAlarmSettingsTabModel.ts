import { useMemo, useState } from 'react'
import { type AlarmStateType, UserRole } from '@/lib/constants'
import type { AlarmSettingsProfile } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { useAlarmSettingsQuery } from '@/hooks/useAlarmQueries'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useUpdateSettingsProfileMutation } from '@/hooks/useSettingsQueries'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { ARM_MODE_OPTIONS } from '@/pages/settings/settingsUtils'

export type AlarmSettingsDraft = {
  codeArmRequired: boolean
  availableArmingStates: AlarmStateType[]
}

function draftFromSettings(settings: AlarmSettingsProfile): AlarmSettingsDraft {
  return {
    codeArmRequired: Boolean(settings.codeArmRequired),
    availableArmingStates: Array.isArray(settings.availableArmingStates) ? settings.availableArmingStates : [],
  }
}

function parseDraft(
  draft: AlarmSettingsDraft
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const modes = draft.availableArmingStates.filter((s) => ARM_MODE_OPTIONS.includes(s))
  if (modes.length === 0) return { ok: false, error: 'Select at least one arm mode.' }

  return {
    ok: true,
    value: {
      codeArmRequired: draft.codeArmRequired,
      availableArmingStates: modes,
    },
  }
}

export function useAlarmSettingsTabModel() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  const settingsQuery = useAlarmSettingsQuery()
  const updateMutation = useUpdateSettingsProfileMutation()

  const settings = settingsQuery.data ?? null
  const isLoading = settingsQuery.isLoading || updateMutation.isPending

  const initialDraft = useMemo(() => {
    if (!settings) return null
    return draftFromSettings(settings)
  }, [settings])

  const { draft, setDraft, resetToInitial } = useDraftFromQuery<AlarmSettingsDraft>(initialDraft)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reset = () => {
    resetToInitial()
    setError(null)
    setNotice(null)
  }

  const save = async () => {
    if (!settings || !draft) return
    setError(null)
    setNotice(null)

    const parsed = parseDraft(draft)
    if (!parsed.ok) {
      setError(parsed.error)
      return
    }

    try {
      await updateMutation.mutateAsync({
        id: settings.id,
        changes: {
          entries: [
            { key: 'code_arm_required', value: parsed.value.codeArmRequired },
            { key: 'available_arming_states', value: parsed.value.availableArmingStates },
          ],
        },
      })

      setNotice('Saved alarm settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save alarm settings')
    }
  }

  const loadError = getErrorMessage(settingsQuery.error) || null

  return {
    isAdmin,
    settingsQuery,
    settings,
    isLoading,
    draft,
    setDraft,
    initialDraft,
    error,
    notice,
    loadError,
    reset,
    save,
  }
}
