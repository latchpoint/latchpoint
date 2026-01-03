import { Button } from '@/components/ui/button'
import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { IconButton } from '@/components/ui/icon-button'
import { Pill } from '@/components/ui/pill'
import { X } from 'lucide-react'
import { alarmStateOptions, uniqueStrings, type AlarmStateConditionRow } from '@/features/rules/builder'

type Props = {
  row: AlarmStateConditionRow
  isSaving: boolean
  pickerValue: string
  setPickerValue: (next: string) => void
  onChange: (next: AlarmStateConditionRow) => void
}

export function AlarmStateInConditionFields({ row, isSaving, pickerValue, setPickerValue, onChange }: Props) {
  return (
    <div className="space-y-2">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Allowed alarm states <HelpTip className="ml-1" content="This condition matches if the current alarm state is in the selected list." />
        </label>
        <div className="flex gap-2">
          <DatalistInput
            listId={`alarm-state-options-${row.id}`}
            options={[...alarmStateOptions]}
            value={pickerValue}
            onChange={(e) => setPickerValue(e.target.value)}
            placeholder="armed_away"
            disabled={isSaving}
          />
          <Button
            type="button"
            variant="outline"
            disabled={isSaving}
            onClick={() => {
              const toAdd = pickerValue.trim()
              if (!toAdd) return
              onChange({ ...row, states: uniqueStrings([...row.states, toAdd]) })
              setPickerValue('')
            }}
          >
            Add
          </Button>
        </div>
        {(row.states || []).length ? (
          <div className="flex flex-wrap gap-1 pt-1">
            {row.states.map((st) => (
              <Pill key={st} variant="muted" className="flex items-center gap-1">
                <span>{st}</span>
                <IconButton
                  type="button"
                  variant="ghost"
                  aria-label={`Remove state ${st}`}
                  onClick={() => onChange({ ...row, states: row.states.filter((x) => x !== st) })}
                >
                  <X className="h-3 w-3" />
                </IconButton>
              </Pill>
            ))}
          </div>
        ) : (
          <div className="pt-1 text-xs text-muted-foreground">No states selected.</div>
        )}
      </div>
    </div>
  )
}

