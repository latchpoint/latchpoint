import type React from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'

import { getSelectValue } from '@/lib/formHelpers'
import { isWhenOperator } from '@/lib/typeGuards'
import {
  uniqueId,
  type ConditionRow,
  type WhenOperator,
} from '@/features/rules/builder'
import { WhenConditionRow } from '@/features/rules/components/when/WhenConditionRow'

type EntitySourceFilter = 'all' | 'home_assistant' | 'zwavejs' | 'zigbee2mqtt'

type FrigateOptions = {
  isLoading: boolean
  hasError: boolean
  knownCameras: string[]
  zonesByCamera: Record<string, string[]>
}

type Props = {
  whenOperator: WhenOperator
  setWhenOperator: (next: WhenOperator) => void
  forSecondsText: string
  setForSecondsText: (next: string) => void

  entitySourceFilter: EntitySourceFilter
  setEntitySourceFilter: (next: EntitySourceFilter) => void

  conditions: ConditionRow[]
  setConditions: React.Dispatch<React.SetStateAction<ConditionRow[]>>
  isSaving: boolean

  entityIdOptions: string[]
  entityIdSet: Set<string>
  entitiesLength: number

  alarmStatePickerByConditionId: Record<string, string>
  setAlarmStatePickerByConditionId: React.Dispatch<React.SetStateAction<Record<string, string>>>
  frigateCameraPickerByConditionId: Record<string, string>
  setFrigateCameraPickerByConditionId: React.Dispatch<React.SetStateAction<Record<string, string>>>
  frigateZonePickerByConditionId: Record<string, string>
  setFrigateZonePickerByConditionId: React.Dispatch<React.SetStateAction<Record<string, string>>>

  frigateOptions: FrigateOptions
}

function isEntitySourceFilter(value: string): value is EntitySourceFilter {
  return value === 'all' || value === 'home_assistant' || value === 'zwavejs' || value === 'zigbee2mqtt'
}

export function WhenBuilderCard({
  whenOperator,
  setWhenOperator,
  forSecondsText,
  setForSecondsText,
  entitySourceFilter,
  setEntitySourceFilter,
  conditions,
  setConditions,
  isSaving,
  entityIdOptions,
  entityIdSet,
  entitiesLength,
  alarmStatePickerByConditionId,
  setAlarmStatePickerByConditionId,
  frigateCameraPickerByConditionId,
  setFrigateCameraPickerByConditionId,
  frigateZonePickerByConditionId,
  setFrigateZonePickerByConditionId,
  frigateOptions,
}: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          When <HelpTip className="ml-1" content="The condition(s) that must match for the rule to fire." />
        </CardTitle>
        <CardDescription>Match on entity state (equals) with AND/OR and optional “for”.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">
              Operator <HelpTip className="ml-1" content="All = AND. Any = OR." />
            </label>
            <Select
              size="sm"
              value={whenOperator}
              onChange={(e) => setWhenOperator(getSelectValue(e, isWhenOperator, 'all'))}
            >
              <option value="all">All (AND)</option>
              <option value="any">Any (OR)</option>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">
              For seconds (optional){' '}
              <HelpTip
                className="ml-1"
                content="Requires the whole condition group to remain true continuously for this many seconds."
              />
            </label>
            <Input value={forSecondsText} onChange={(e) => setForSecondsText(e.target.value)} placeholder="e.g., 300" />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">
              Entity source{' '}
              <HelpTip className="ml-1" content="Filter autocomplete to Home Assistant, Z-Wave JS, or Zigbee2MQTT entities." />
            </label>
            <Select
              size="sm"
              value={entitySourceFilter}
              onChange={(e) => setEntitySourceFilter(getSelectValue(e, isEntitySourceFilter, 'all'))}
            >
              <option value="all">All</option>
              <option value="home_assistant">Home Assistant</option>
              <option value="zwavejs">Z-Wave JS</option>
              <option value="zigbee2mqtt">Zigbee2MQTT</option>
            </Select>
          </div>

          <div className="flex items-end text-xs text-muted-foreground">
            {conditions.length} condition{conditions.length === 1 ? '' : 's'}
          </div>
        </div>

        <div className="space-y-2">
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  setConditions((prev) => [
                    ...prev,
                    { id: uniqueId(), type: 'alarm_state_in', negate: false, states: ['armed_away'] },
                    {
                      id: uniqueId(),
                      type: 'frigate_person_detected',
                      negate: false,
                      cameras: ['backyard'],
                      zones: [],
                      withinSeconds: '10',
                      minConfidencePct: '90',
                      aggregation: 'max',
                      percentile: '90',
                      onUnavailable: 'treat_as_no_match',
                    },
                  ])
                }
                disabled={isSaving}
              >
                Add preset: armed_away + Frigate person
              </Button>
              <div className="flex items-center text-xs text-muted-foreground">
                Presets are editable; update camera/zone/threshold to match your setup.
              </div>
            </div>
          </div>

          {conditions.map((row) => {
            return (
              <WhenConditionRow
                key={row.id}
                row={row}
                conditionsCount={conditions.length}
                isSaving={isSaving}
                entityIdOptions={entityIdOptions}
                entityIdSet={entityIdSet}
                entitiesLength={entitiesLength}
                alarmStatePicker={alarmStatePickerByConditionId[row.id] || ''}
                setAlarmStatePicker={(next) => setAlarmStatePickerByConditionId((prev) => ({ ...prev, [row.id]: next }))}
                frigateCameraPicker={frigateCameraPickerByConditionId[row.id] || ''}
                setFrigateCameraPicker={(next) => setFrigateCameraPickerByConditionId((prev) => ({ ...prev, [row.id]: next }))}
                frigateZonePicker={frigateZonePickerByConditionId[row.id] || ''}
                setFrigateZonePicker={(next) => setFrigateZonePickerByConditionId((prev) => ({ ...prev, [row.id]: next }))}
                frigateOptions={frigateOptions}
                onRemove={() => setConditions((prev) => prev.filter((c) => c.id !== row.id))}
                onUpdate={(updater) => setConditions((prev) => prev.map((c) => (c.id === row.id ? updater(c) : c)))}
              />
            )
          })}

          <Button
            type="button"
            variant="outline"
            onClick={() =>
              setConditions((prev) => [...prev, { id: uniqueId(), type: 'entity_state', entityId: '', equals: 'on', negate: false }])
            }
            disabled={isSaving}
          >
            Add condition
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
