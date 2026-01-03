import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { uniqueStrings, type FrigatePersonConditionRow } from '@/features/rules/builder'
import { FrigateStringListPicker } from '@/features/rules/components/when/FrigateStringListPicker'

type FrigateOptions = {
  isLoading: boolean
  hasError: boolean
  knownCameras: string[]
  zonesByCamera: Record<string, string[]>
}

type Props = {
  row: FrigatePersonConditionRow
  isSaving: boolean
  pickerCamera: string
  setPickerCamera: (next: string) => void
  pickerZone: string
  setPickerZone: (next: string) => void
  frigateOptions: FrigateOptions
  onChange: (next: FrigatePersonConditionRow) => void
}

export function FrigatePersonDetectedConditionFields({
  row,
  isSaving,
  pickerCamera,
  setPickerCamera,
  pickerZone,
  setPickerZone,
  frigateOptions,
  onChange,
}: Props) {
  const knownCameras = frigateOptions.knownCameras
  const zonesByCamera = frigateOptions.zonesByCamera
  const zoneOptions =
    row.cameras.length === 1 ? zonesByCamera[row.cameras[0]] ?? [] : Array.from(new Set(Object.values(zonesByCamera).flat())).sort()

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <FrigateStringListPicker
          label="Cameras"
          help="Frigate cameras to match (at least one required)."
          listId={`frigate-cameras-${row.id}`}
          options={knownCameras}
          placeholder="backyard"
          pickerValue={pickerCamera}
          setPickerValue={setPickerCamera}
          values={row.cameras}
          setValues={(next) => onChange({ ...row, cameras: uniqueStrings(next) })}
          disabled={isSaving}
        />

        <FrigateStringListPicker
          label="Zones (optional)"
          help="If set, requires the Frigate event zones to overlap (any match). Leave empty to ignore zones."
          listId={`frigate-zones-${row.id}`}
          options={zoneOptions}
          placeholder="yard"
          pickerValue={pickerZone}
          setPickerValue={setPickerZone}
          values={row.zones}
          setValues={(next) => onChange({ ...row, zones: uniqueStrings(next) })}
          disabled={isSaving}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <FormField size="compact" label="Window (s)" htmlFor={`frigate-within-${row.id}`} help="Look back this many seconds for matching person detections.">
          <Input
            id={`frigate-within-${row.id}`}
            value={row.withinSeconds}
            onChange={(e) => onChange({ ...row, withinSeconds: e.target.value })}
            disabled={isSaving}
          />
        </FormField>
        <FormField size="compact" label="Min conf (%)" htmlFor={`frigate-minconf-${row.id}`} help="Minimum confidence required (0–100).">
          <Input
            id={`frigate-minconf-${row.id}`}
            value={row.minConfidencePct}
            onChange={(e) => onChange({ ...row, minConfidencePct: e.target.value })}
            disabled={isSaving}
          />
        </FormField>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Aggregation <HelpTip className="ml-1" content="How to combine multiple detections in the window: Max, Latest, or Percentile." />
          </label>
          <Select
            size="sm"
            value={row.aggregation}
            onChange={(e) => onChange({ ...row, aggregation: e.target.value as FrigatePersonConditionRow['aggregation'] })}
            disabled={isSaving}
          >
            <option value="max">Max</option>
            <option value="latest">Latest</option>
            <option value="percentile">Percentile</option>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            If Frigate down{' '}
            <HelpTip className="ml-1" content="Controls behavior when MQTT/Frigate is unavailable: either require Frigate (no match), or ignore downtime (match)." />
          </label>
          <Select
            size="sm"
            value={row.onUnavailable}
            onChange={(e) => onChange({ ...row, onUnavailable: e.target.value as FrigatePersonConditionRow['onUnavailable'] })}
            disabled={isSaving}
          >
            <option value="treat_as_no_match">Require Frigate</option>
            <option value="treat_as_match">Ignore if down</option>
          </Select>
        </div>
      </div>

      {row.aggregation === 'percentile' ? (
        <FormField size="compact" label="Percentile" htmlFor={`frigate-percentile-${row.id}`} help="Percentile to evaluate over detections in the window (1–100).">
          <Input
            id={`frigate-percentile-${row.id}`}
            value={row.percentile}
            onChange={(e) => onChange({ ...row, percentile: e.target.value })}
            disabled={isSaving}
          />
        </FormField>
      ) : null}

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Action <HelpTip className="ml-1" content="How to treat a person detection for rule matching." />
        </label>
        <Textarea
          className="min-h-[88px] font-mono text-xs"
          value={JSON.stringify(
            {
              cameras: row.cameras,
              zones: row.zones,
              withinSeconds: row.withinSeconds,
              minConfidencePct: row.minConfidencePct,
              aggregation: row.aggregation,
              ...(row.aggregation === 'percentile' ? { percentile: row.percentile } : {}),
              onUnavailable: row.onUnavailable,
            },
            null,
            2
          )}
          readOnly
          spellCheck={false}
        />
        <div className="text-xs text-muted-foreground">
          {frigateOptions.isLoading
            ? 'Loading Frigate cameras/zones…'
            : frigateOptions.hasError
              ? 'Frigate options unavailable.'
              : knownCameras.length
                ? `Known cameras: ${knownCameras.join(', ')}`
                : 'No Frigate detections ingested yet.'}
        </div>
      </div>
    </div>
  )
}
