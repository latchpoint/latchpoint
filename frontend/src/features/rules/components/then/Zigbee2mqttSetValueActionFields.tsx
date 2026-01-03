import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

type Props = {
  entityId: string
  valueJson: string
  isSaving?: boolean
  entityIdOptions: string[]
  onChange: (patch: { entityId?: string; valueJson?: string }) => void
}

export function Zigbee2mqttSetValueActionFields({ entityId, valueJson, isSaving, entityIdOptions, onChange }: Props) {
  const z2mOptions = entityIdOptions.filter((id) => id.startsWith('z2m_') || id.startsWith('z2m.'))

  return (
    <>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Entity</label>
        <Select size="sm" value={entityId} onChange={(e) => onChange({ entityId: e.target.value })} disabled={isSaving}>
          <option value="">Select entity…</option>
          {z2mOptions.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1 md:col-span-2">
        <label className="text-xs text-muted-foreground">Value (JSON)</label>
        <Textarea
          value={valueJson}
          onChange={(e) => onChange({ valueJson: e.target.value })}
          disabled={isSaving}
          className="min-h-20 font-mono text-xs"
          placeholder={'true\n"ON"\n200\n{"state":"ON","brightness":200}'}
        />
      </div>
    </>
  )
}

