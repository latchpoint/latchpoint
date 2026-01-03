import { Select } from '@/components/ui/select'

type Props = {
  entityId: string
  state: 'on' | 'off'
  isSaving?: boolean
  entityIdOptions: string[]
  onChange: (patch: { entityId?: string; state?: 'on' | 'off' }) => void
}

export function Zigbee2mqttSwitchActionFields({ entityId, state, isSaving, entityIdOptions, onChange }: Props) {
  const z2mOptions = entityIdOptions.filter((id) => id.startsWith('z2m_') || id.startsWith('z2m.'))
  const stateEntityOptions = z2mOptions.filter((id) => id.endsWith('_state'))

  return (
    <>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Device</label>
        <Select size="sm" value={entityId} onChange={(e) => onChange({ entityId: e.target.value })} disabled={isSaving}>
          <option value="">Select entity…</option>
          {(stateEntityOptions.length ? stateEntityOptions : z2mOptions).map((id) => (
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
    </>
  )
}

