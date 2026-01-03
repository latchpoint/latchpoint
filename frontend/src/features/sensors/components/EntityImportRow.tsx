import { useMemo } from 'react'

import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

type Props = {
  entityId: string
  name: string
  deviceClass?: string | null
  state?: string | null

  alreadyImported: boolean
  importedSensorId?: number | null

  checked: boolean
  onCheckedChange: (next: boolean) => void

  nameOverride: string
  onNameOverrideChange: (next: string) => void

  suggestedEntry: boolean
  entry: boolean
  onEntryChange: (next: boolean) => void

  entryHelpOpen: boolean
  onToggleEntryHelp: () => void
  entrySensorHelp: string
  entrySensorSuggestedHelp: string
}

function toDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, '_')
}

export function EntityImportRow({
  entityId,
  name,
  deviceClass,
  state,
  alreadyImported,
  importedSensorId,
  checked,
  onCheckedChange,
  nameOverride,
  onNameOverrideChange,
  suggestedEntry,
  entry,
  onEntryChange,
  entryHelpOpen,
  onToggleEntryHelp,
  entrySensorHelp,
  entrySensorSuggestedHelp,
}: Props) {
  const domId = useMemo(() => toDomId(entityId), [entityId])
  const helpId = `entry-sensor-help-${domId}`
  const entryLabelId = `entry-sensor-label-${domId}`

  return (
    <div className="rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <label className="flex items-start gap-3">
          <Checkbox
            className="mt-1"
            checked={checked}
            disabled={alreadyImported}
            onChange={(e) => onCheckedChange(e.target.checked)}
          />
          <div>
            <div className="font-medium">{name}</div>
            <div className="text-xs text-muted-foreground">
              {entityId}
              {deviceClass ? ` • ${deviceClass}` : ''}
              {state ? ` • ${state}` : ''}
            </div>
            {alreadyImported ? (
              <div className="mt-1 text-xs text-muted-foreground">
                Already imported{importedSensorId ? ` • ID: ${importedSensorId}` : ''}
              </div>
            ) : null}
          </div>
        </label>
      </div>

      {checked && !alreadyImported ? (
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <div className="space-y-1 md:col-span-2">
            <label className="text-xs text-muted-foreground">Sensor name</label>
            <Input value={nameOverride} onChange={(e) => onNameOverrideChange(e.target.value)} />
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <label className="text-xs text-muted-foreground">Entry sensor</label>
              <button
                type="button"
                className="text-xs text-muted-foreground underline"
                aria-controls={helpId}
                aria-expanded={entryHelpOpen}
                onClick={onToggleEntryHelp}
              >
                Help
              </button>
            </div>
            <div className="flex items-center gap-2">
              <Switch checked={entry} onCheckedChange={onEntryChange} aria-labelledby={entryLabelId} />
              <span id={entryLabelId} className="text-sm">
                {suggestedEntry ? 'On (suggested)' : 'Off'}
              </span>
            </div>
            {entryHelpOpen ? (
              <div id={helpId} className="rounded-md bg-muted p-2 text-xs text-muted-foreground">
                <div>{entrySensorHelp}</div>
                <div className="mt-1">{entrySensorSuggestedHelp}</div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

