import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { HelpTip } from '@/components/ui/help-tip'
import { Select } from '@/components/ui/select'
import type { ConditionRow } from '@/features/rules/builder'
import { AlarmStateInConditionFields } from '@/features/rules/components/when/AlarmStateInConditionFields'
import { EntityStateConditionFields } from '@/features/rules/components/when/EntityStateConditionFields'
import { FrigatePersonDetectedConditionFields } from '@/features/rules/components/when/FrigatePersonDetectedConditionFields'

type FrigateOptions = {
  isLoading: boolean
  hasError: boolean
  knownCameras: string[]
  zonesByCamera: Record<string, string[]>
}

type Props = {
  row: ConditionRow
  conditionsCount: number
  isSaving: boolean
  entityIdOptions: string[]
  entityIdSet: Set<string>
  entitiesLength: number
  alarmStatePicker: string
  setAlarmStatePicker: (next: string) => void
  frigateCameraPicker: string
  setFrigateCameraPicker: (next: string) => void
  frigateZonePicker: string
  setFrigateZonePicker: (next: string) => void
  frigateOptions: FrigateOptions
  onRemove: () => void
  onUpdate: (updater: (prev: ConditionRow) => ConditionRow) => void
}

export function WhenConditionRow({
  row,
  conditionsCount,
  isSaving,
  entityIdOptions,
  entityIdSet,
  entitiesLength,
  alarmStatePicker,
  setAlarmStatePicker,
  frigateCameraPicker,
  setFrigateCameraPicker,
  frigateZonePicker,
  setFrigateZonePicker,
  frigateOptions,
  onRemove,
  onUpdate,
}: Props) {
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">Condition</div>
        <Button type="button" variant="outline" disabled={conditionsCount <= 1} onClick={onRemove}>
          Remove
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Type <HelpTip className="ml-1" content="Choose the condition type." />
          </label>
          <Select
            size="sm"
            value={row.type}
            onChange={(e) => {
              const nextType = e.target.value as ConditionRow['type']
              onUpdate((c) => {
                if (nextType === c.type) return c
                if (nextType === 'entity_state') return { id: c.id, type: 'entity_state', entityId: '', equals: 'on', negate: false }
                if (nextType === 'alarm_state_in') return { id: c.id, type: 'alarm_state_in', negate: false, states: [] }
                return {
                  id: c.id,
                  type: 'frigate_person_detected',
                  negate: false,
                  cameras: [],
                  zones: [],
                  withinSeconds: '10',
                  minConfidencePct: '90',
                  aggregation: 'max',
                  percentile: '90',
                  onUnavailable: 'treat_as_no_match',
                }
              })
            }}
            disabled={isSaving}
          >
            <option value="entity_state">Entity state</option>
            <option value="alarm_state_in">Alarm state</option>
            <option value="frigate_person_detected">Frigate person detected</option>
          </Select>
        </div>

        <div className="flex items-end gap-2 md:col-span-2">
          <Checkbox
            id={`cond-negate-${row.id}`}
            checked={row.negate}
            onChange={(e) => onUpdate((c) => ({ ...c, negate: e.target.checked }))}
            disabled={isSaving}
          />
          <label htmlFor={`cond-negate-${row.id}`} className="text-sm">
            NOT
          </label>
        </div>
      </div>

      {row.type === 'entity_state' ? (
        <EntityStateConditionFields
          row={row}
          isSaving={isSaving}
          entityIdOptions={entityIdOptions}
          entityIdSet={entityIdSet}
          entitiesLength={entitiesLength}
          onChange={(next) => onUpdate(() => next)}
        />
      ) : row.type === 'alarm_state_in' ? (
        <AlarmStateInConditionFields
          row={row}
          isSaving={isSaving}
          pickerValue={alarmStatePicker}
          setPickerValue={setAlarmStatePicker}
          onChange={(next) => onUpdate(() => next)}
        />
      ) : (
        <FrigatePersonDetectedConditionFields
          row={row}
          isSaving={isSaving}
          pickerCamera={frigateCameraPicker}
          setPickerCamera={setFrigateCameraPicker}
          pickerZone={frigateZonePicker}
          setPickerZone={setFrigateZonePicker}
          frigateOptions={frigateOptions}
          onChange={(next) => onUpdate(() => next)}
        />
      )}
    </div>
  )
}

