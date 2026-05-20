import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { SectionCard } from '@/components/ui/section-card'
import { Switch } from '@/components/ui/switch'
import { AlarmStateLabels } from '@/lib/constants'
import { ARM_MODE_OPTIONS, ARM_MODE_TOOLTIPS, toggleState } from '@/pages/settings/settingsUtils'
import type { AlarmSettingsDraft } from '@/features/alarmSettings/hooks/useAlarmSettingsTabModel'

type Props = {
  isAdmin: boolean
  isLoading: boolean
  hasInitialDraft: boolean
  draft: AlarmSettingsDraft
  onRefresh: () => void
  onReset: () => void
  onSave: () => void
  onSetDraft: (updater: (prev: AlarmSettingsDraft | null) => AlarmSettingsDraft | null) => void
}

export function AlarmArmModesCard({
  isAdmin,
  isLoading,
  hasInitialDraft,
  draft,
  onRefresh,
  onReset,
  onSave,
  onSetDraft,
}: Props) {
  return (
    <SectionCard
      title="Arm modes"
      description="Choose which arming modes are available in the UI. Exit-delay durations are configured per-rule in the rule builder (ADR-0095)."
      actions={
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onRefresh} disabled={isLoading}>
            Refresh
          </Button>
          <Button type="button" variant="secondary" onClick={onReset} disabled={isLoading || !hasInitialDraft}>
            Reset
          </Button>
          <Button type="button" onClick={onSave} disabled={isLoading || !isAdmin}>
            Save
          </Button>
        </div>
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        {ARM_MODE_OPTIONS.map((state) => {
          const checked = draft.availableArmingStates.includes(state)
          return (
            <label key={state} className="flex items-center gap-3 rounded-md border border-input px-3 py-2">
              <Checkbox
                checked={checked}
                onChange={() =>
                  onSetDraft((prev) =>
                    prev ? { ...prev, availableArmingStates: toggleState(prev.availableArmingStates, state) } : prev,
                  )
                }
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

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <FormField
          label="Code required to arm"
          help="If disabled, arming does not require a PIN (disarm still requires a code)."
        >
          <Switch
            checked={draft.codeArmRequired}
            onCheckedChange={(checked) =>
              onSetDraft((prev) => (prev ? { ...prev, codeArmRequired: checked } : prev))
            }
            disabled={!isAdmin || isLoading}
          />
        </FormField>
      </div>
    </SectionCard>
  )
}
