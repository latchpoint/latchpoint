import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'

type Props = {
  entityId: string
  state: 'on' | 'off'
  brightness: string
  isSaving?: boolean
  entityIdOptions: string[]
  onChange: (patch: { entityId?: string; state?: 'on' | 'off'; brightness?: string }) => void
}

export function Zigbee2mqttLightActionFields({ entityId, state, brightness, isSaving, entityIdOptions, onChange }: Props) {
  const z2mOptions = entityIdOptions.filter((id) => id.startsWith('z2m_') || id.startsWith('z2m.'))

  return (
    <>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Device</label>
        <Select size="sm" value={entityId} onChange={(e) => onChange({ entityId: e.target.value })} disabled={isSaving}>
          <option value="">Select entity…</option>
          {z2mOptions.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">State</label>
        <Select size="sm" value={state} onChange={(e) => onChange({ state: e.target.value as 'on' | 'off' })} disabled={isSaving}>
          <option value="on">On</option>
          <option value="off">Off</option>
        </Select>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Brightness (0–255, optional)</label>
        <Input value={brightness} onChange={(e) => onChange({ brightness: e.target.value })} placeholder="e.g., 200" disabled={isSaving} />
      </div>
    </>
  )
}

