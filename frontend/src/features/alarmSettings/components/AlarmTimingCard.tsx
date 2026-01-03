import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { SectionCard } from '@/components/ui/section-card'
import { AlarmState, AlarmStateLabels } from '@/lib/constants'
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

export function AlarmTimingCard({ isAdmin, isLoading, hasInitialDraft, draft, onRefresh, onReset, onSave, onSetDraft }: Props) {
  return (
    <SectionCard
      title="Timing"
      description="Simple alarm timings (seconds)."
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
      <div className="grid gap-4 md:grid-cols-3">
        <FormField
          label="Entry delay"
          htmlFor="delayTime"
          help="How long you have to disarm after an entry-point sensor trips (e.g., front door) before the alarm triggers."
        >
          <Input id="delayTime" type="number" min={0} inputMode="numeric" value={draft.delayTime} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, delayTime: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>

        <FormField label="Exit delay (default)" htmlFor="armingTime" help="Fallback countdown after you arm before the alarm is active. Per-mode exit delays below override this.">
          <Input id="armingTime" type="number" min={0} inputMode="numeric" value={draft.armingTime} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, armingTime: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>

        <FormField label="Trigger time" htmlFor="triggerTime" help="How long the alarm remains in the Triggered state before it returns to the previous armed state (or disarms, if configured).">
          <Input id="triggerTime" type="number" min={0} inputMode="numeric" value={draft.triggerTime} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, triggerTime: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <FormField label={`Exit delay: ${AlarmStateLabels[AlarmState.ARMED_HOME]}`} htmlFor="armingTimeHome" help="Countdown after arming Home before it becomes active.">
          <Input id="armingTimeHome" type="number" min={0} inputMode="numeric" value={draft.armingTimeHome} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, armingTimeHome: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>

        <FormField label={`Exit delay: ${AlarmStateLabels[AlarmState.ARMED_AWAY]}`} htmlFor="armingTimeAway" help="Countdown after arming Away before it becomes active.">
          <Input id="armingTimeAway" type="number" min={0} inputMode="numeric" value={draft.armingTimeAway} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, armingTimeAway: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>

        <FormField label={`Exit delay: ${AlarmStateLabels[AlarmState.ARMED_NIGHT]}`} htmlFor="armingTimeNight" help="Countdown after arming Night before it becomes active.">
          <Input id="armingTimeNight" type="number" min={0} inputMode="numeric" value={draft.armingTimeNight} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, armingTimeNight: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>

        <FormField label={`Exit delay: ${AlarmStateLabels[AlarmState.ARMED_VACATION]}`} htmlFor="armingTimeVacation" help="Countdown after arming Vacation before it becomes active.">
          <Input id="armingTimeVacation" type="number" min={0} inputMode="numeric" value={draft.armingTimeVacation} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, armingTimeVacation: e.target.value } : prev))} disabled={!isAdmin || isLoading} />
        </FormField>
      </div>
    </SectionCard>
  )
}

