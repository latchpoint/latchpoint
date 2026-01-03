import { Checkbox } from '@/components/ui/checkbox'
import { HelpTip } from '@/components/ui/help-tip'
import { SectionCard } from '@/components/ui/section-card'
import { AlarmStateLabels } from '@/lib/constants'
import { ARM_MODE_OPTIONS, ARM_MODE_TOOLTIPS, toggleState } from '@/pages/settings/settingsUtils'
import type { AlarmSettingsDraft } from '@/features/alarmSettings/hooks/useAlarmSettingsTabModel'

type Props = {
  isAdmin: boolean
  isLoading: boolean
  draft: AlarmSettingsDraft
  onSetDraft: (updater: (prev: AlarmSettingsDraft | null) => AlarmSettingsDraft | null) => void
}

export function AlarmArmModesCard({ isAdmin, isLoading, draft, onSetDraft }: Props) {
  return (
    <SectionCard title="Arm modes" description="Choose which arming modes are available in the UI.">
      <div className="grid gap-3 md:grid-cols-2">
        {ARM_MODE_OPTIONS.map((state) => {
          const checked = draft.availableArmingStates.includes(state)
          return (
            <label key={state} className="flex items-center gap-3 rounded-md border border-input px-3 py-2">
              <Checkbox
                checked={checked}
                onChange={() => onSetDraft((prev) => (prev ? { ...prev, availableArmingStates: toggleState(prev.availableArmingStates, state) } : prev))}
                disabled={!isAdmin || isLoading}
              />
              <div className="flex items-center gap-2">
                <div className="text-sm">{AlarmStateLabels[state]}</div>
                <HelpTip content={ARM_MODE_TOOLTIPS[state] || 'Arming mode.'} />
              </div>
            </label>
          )
        })}
      </div>
    </SectionCard>
  )
}

