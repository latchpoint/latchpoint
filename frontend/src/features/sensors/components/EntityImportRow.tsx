import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'

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
}: Props) {
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
        <div className="mt-3">
          <label className="text-xs text-muted-foreground">Sensor name</label>
          <Input value={nameOverride} onChange={(e) => onNameOverrideChange(e.target.value)} />
        </div>
      ) : null}
    </div>
  )
}
