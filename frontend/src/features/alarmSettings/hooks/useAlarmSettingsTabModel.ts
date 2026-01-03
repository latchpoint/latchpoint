import { useMemo, useState } from 'react'
import { AlarmState, AlarmStateLabels, type AlarmStateType, UserRole } from '@/lib/constants'
import type { AlarmSettingsProfile } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { useAlarmSettingsQuery } from '@/hooks/useAlarmQueries'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useUpdateSettingsProfileMutation } from '@/hooks/useSettingsQueries'
import { useDraftFromQuery } from '@/features/settings/hooks/useDraftFromQuery'
import { ARM_MODE_OPTIONS, normalizeStateOverrides, parseNonNegativeInt } from '@/pages/settings/settingsUtils'

export type AlarmSettingsDraft = {
  delayTime: string
  armingTime: string
  armingTimeHome: string
  armingTimeAway: string
  armingTimeNight: string
  armingTimeVacation: string
  triggerTime: string
  disarmAfterTrigger: boolean
  codeArmRequired: boolean
  availableArmingStates: AlarmStateType[]
}

function draftFromSettings(settings: AlarmSettingsProfile): AlarmSettingsDraft {
  const getOverrideInt = (value: unknown): number | null => {
    if (typeof value !== 'number' || !Number.isFinite(value) || Number.isNaN(value)) return null
    return Math.max(0, Math.floor(value))
  }

  const armingTimeDefault = getOverrideInt(settings.armingTime) ?? 0
  const overrides = normalizeStateOverrides(settings.stateOverrides ?? {})
  const armingTimeHome = getOverrideInt(overrides[AlarmState.ARMED_HOME]?.armingTime) ?? armingTimeDefault
  const armingTimeAway = getOverrideInt(overrides[AlarmState.ARMED_AWAY]?.armingTime) ?? armingTimeDefault
  const armingTimeNight = getOverrideInt(overrides[AlarmState.ARMED_NIGHT]?.armingTime) ?? armingTimeDefault
  const armingTimeVacation = getOverrideInt(overrides[AlarmState.ARMED_VACATION]?.armingTime) ?? armingTimeDefault

  return {
    delayTime: String(settings.delayTime ?? 0),
    armingTime: String(settings.armingTime ?? 0),
    armingTimeHome: String(armingTimeHome),
    armingTimeAway: String(armingTimeAway),
    armingTimeNight: String(armingTimeNight),
    armingTimeVacation: String(armingTimeVacation),
    triggerTime: String(settings.triggerTime ?? 0),
    disarmAfterTrigger: Boolean(settings.disarmAfterTrigger),
    codeArmRequired: Boolean(settings.codeArmRequired),
    availableArmingStates: Array.isArray(settings.availableArmingStates) ? settings.availableArmingStates : [],
  }
}

function parseDraft(
  draft: AlarmSettingsDraft
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const delayTime = parseNonNegativeInt('Entry delay', draft.delayTime)
  if (!delayTime.ok) return delayTime
  const armingTime = parseNonNegativeInt('Exit delay', draft.armingTime)
  if (!armingTime.ok) return armingTime
  const armingTimeHome = parseNonNegativeInt(`Exit delay (${AlarmStateLabels[AlarmState.ARMED_HOME]})`, draft.armingTimeHome)
  if (!armingTimeHome.ok) return armingTimeHome
  const armingTimeAway = parseNonNegativeInt(`Exit delay (${AlarmStateLabels[AlarmState.ARMED_AWAY]})`, draft.armingTimeAway)
  if (!armingTimeAway.ok) return armingTimeAway
  const armingTimeNight = parseNonNegativeInt(`Exit delay (${AlarmStateLabels[AlarmState.ARMED_NIGHT]})`, draft.armingTimeNight)
  if (!armingTimeNight.ok) return armingTimeNight
  const armingTimeVacation = parseNonNegativeInt(`Exit delay (${AlarmStateLabels[AlarmState.ARMED_VACATION]})`, draft.armingTimeVacation)
  if (!armingTimeVacation.ok) return armingTimeVacation
  const triggerTime = parseNonNegativeInt('Trigger time', draft.triggerTime)
  if (!triggerTime.ok) return triggerTime

  const modes = draft.availableArmingStates.filter((s) => ARM_MODE_OPTIONS.includes(s))
  if (modes.length === 0) return { ok: false, error: 'Select at least one arm mode.' }

  return {
    ok: true,
    value: {
      delayTime: delayTime.value,
      armingTime: armingTime.value,
      armingTimeHome: armingTimeHome.value,
      armingTimeAway: armingTimeAway.value,
      armingTimeNight: armingTimeNight.value,
      armingTimeVacation: armingTimeVacation.value,
      triggerTime: triggerTime.value,
      disarmAfterTrigger: draft.disarmAfterTrigger,
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
      const existingOverrides = normalizeStateOverrides(settings.stateOverrides ?? {})
      const nextStateOverrides = {
        ...existingOverrides,
        [AlarmState.ARMED_HOME]: { ...(existingOverrides[AlarmState.ARMED_HOME] ?? {}), armingTime: parsed.value.armingTimeHome },
        [AlarmState.ARMED_AWAY]: { ...(existingOverrides[AlarmState.ARMED_AWAY] ?? {}), armingTime: parsed.value.armingTimeAway },
        [AlarmState.ARMED_NIGHT]: { ...(existingOverrides[AlarmState.ARMED_NIGHT] ?? {}), armingTime: parsed.value.armingTimeNight },
        [AlarmState.ARMED_VACATION]: { ...(existingOverrides[AlarmState.ARMED_VACATION] ?? {}), armingTime: parsed.value.armingTimeVacation },
      }

      await updateMutation.mutateAsync({
        id: settings.id,
        changes: {
          entries: [
            { key: 'delay_time', value: parsed.value.delayTime },
            { key: 'arming_time', value: parsed.value.armingTime },
            { key: 'trigger_time', value: parsed.value.triggerTime },
            { key: 'disarm_after_trigger', value: parsed.value.disarmAfterTrigger },
            { key: 'code_arm_required', value: parsed.value.codeArmRequired },
            { key: 'available_arming_states', value: parsed.value.availableArmingStates },
            { key: 'state_overrides', value: nextStateOverrides },
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

