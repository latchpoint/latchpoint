import { FormField } from '@/components/ui/form-field'
import { SectionCard } from '@/components/ui/section-card'
import { Switch } from '@/components/ui/switch'
import type { AlarmSettingsDraft } from '@/features/alarmSettings/hooks/useAlarmSettingsTabModel'

type Props = {
  isAdmin: boolean
  isLoading: boolean
  draft: AlarmSettingsDraft
  onSetDraft: (updater: (prev: AlarmSettingsDraft | null) => AlarmSettingsDraft | null) => void
}

export function AlarmBehaviorCard({ isAdmin, isLoading, draft, onSetDraft }: Props) {
  return (
    <SectionCard title="Behavior" description="Basic behavior toggles.">
      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="Disarm after trigger" help="If enabled, auto-disarm after Trigger time; otherwise return to the previous armed state.">
          <Switch checked={draft.disarmAfterTrigger} onCheckedChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, disarmAfterTrigger: checked } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>

        <FormField label="Code required to arm" help="If disabled, arming does not require a PIN (disarm still requires a code).">
          <Switch checked={draft.codeArmRequired} onCheckedChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, codeArmRequired: checked } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>
      </div>
    </SectionCard>
  )
}

