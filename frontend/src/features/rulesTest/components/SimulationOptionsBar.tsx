import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'

type Props = {
  assumeForSeconds: string
  onAssumeForSecondsChange: (next: string) => void
  alarmState: string
  onAlarmStateChange: (next: string) => void
  showRunButton: boolean
  onRun: () => void
  disabled?: boolean
  assumeLabel?: string
  assumeHelp?: string
}

export function SimulationOptionsBar({
  assumeForSeconds,
  onAssumeForSecondsChange,
  alarmState,
  onAlarmStateChange,
  showRunButton,
  onRun,
  disabled,
  assumeLabel = 'Assume conditions true for (seconds)',
  assumeHelp = "Used only for FOR rules. If set to >= the rule's FOR seconds, the simulator will treat it as satisfied.",
}: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          {assumeLabel}{' '}
          <HelpTip className="ml-1" content={assumeHelp} />
        </label>
        <Input
          value={assumeForSeconds}
          onChange={(e) => onAssumeForSecondsChange(e.target.value)}
          placeholder="e.g., 300"
          inputMode="numeric"
          disabled={disabled}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          {[0, 30, 60, 300].map((v) => (
            <Button
              key={v}
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() => onAssumeForSecondsChange(String(v))}
            >
              {v}s
            </Button>
          ))}
          <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onAssumeForSecondsChange('')}>
            Clear
          </Button>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Alarm state override (optional){' '}
          <HelpTip className="ml-1" content="Overrides the current alarm state for alarm_state_in conditions during simulation only." />
        </label>
        <Select value={alarmState} onChange={(e) => onAlarmStateChange(e.target.value)} disabled={disabled}>
          <option value="">(use current)</option>
          <option value="disarmed">disarmed</option>
          <option value="arming">arming</option>
          <option value="armed_home">armed_home</option>
          <option value="armed_away">armed_away</option>
          <option value="armed_night">armed_night</option>
          <option value="armed_vacation">armed_vacation</option>
          <option value="pending">pending</option>
          <option value="triggered">triggered</option>
        </Select>
      </div>

      <div className="flex items-end justify-end">
        {showRunButton ? (
          <Button type="button" onClick={onRun} disabled={disabled}>
            {disabled ? 'Running…' : 'Run simulation'}
          </Button>
        ) : (
          <div className="text-xs text-muted-foreground">Use “Run baseline + change” above.</div>
        )}
      </div>
    </div>
  )
}
