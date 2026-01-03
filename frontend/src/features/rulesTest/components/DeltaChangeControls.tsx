import { Button } from '@/components/ui/button'
import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'

type Props = {
  listId?: string
  entityIdOptions: string[]
  deltaEntityId: string
  onDeltaEntityIdChange: (next: string) => void
  deltaState: string
  onDeltaStateChange: (next: string) => void
  baselineState?: string | null
  onRunBaselineAndChange: () => void
  disabled?: boolean
}

export function DeltaChangeControls({
  listId = 'rules-test-entity-options',
  entityIdOptions,
  deltaEntityId,
  onDeltaEntityIdChange,
  deltaState,
  onDeltaStateChange,
  baselineState,
  onRunBaselineAndChange,
  disabled,
}: Props) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <div className="space-y-1 md:col-span-2">
        <label className="text-xs text-muted-foreground">
          Entity ID <HelpTip className="ml-1" content="Pick one entity and set a new state to compare baseline vs change." />
        </label>
        <DatalistInput
          listId={listId}
          value={deltaEntityId}
          onChange={(e) => onDeltaEntityIdChange(e.target.value)}
          options={entityIdOptions}
          maxOptions={500}
          placeholder="e.g. binary_sensor.front_door"
          disabled={disabled}
        />
        {deltaEntityId.trim() && baselineState != null && (
          <div className="text-xs text-muted-foreground">Baseline: {baselineState}</div>
        )}
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">State</label>
        <div className="flex items-center gap-2">
          <Input value={deltaState} onChange={(e) => onDeltaStateChange(e.target.value)} disabled={disabled} />
          <Select value={deltaState} onChange={(e) => onDeltaStateChange(e.target.value)} disabled={disabled}>
            <option value="on">on</option>
            <option value="off">off</option>
            <option value="open">open</option>
            <option value="closed">closed</option>
            <option value="locked">locked</option>
            <option value="unlocked">unlocked</option>
          </Select>
        </div>
        <div className="flex flex-wrap gap-1 pt-1">
          {['on', 'off', 'open', 'closed', 'locked', 'unlocked'].map((v) => (
            <button
              key={v}
              type="button"
              className="rounded border border-input bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              disabled={disabled}
              onClick={() => onDeltaStateChange(v)}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
      <div className="md:col-span-3 flex justify-end">
        <Button type="button" onClick={onRunBaselineAndChange} disabled={disabled || !deltaEntityId.trim()}>
          Run baseline + change
        </Button>
      </div>
    </div>
  )
}
