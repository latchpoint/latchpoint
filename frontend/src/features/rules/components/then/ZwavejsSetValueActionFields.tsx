import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type Props = {
  nodeId: string
  commandClass: string
  endpoint: string
  property: string
  propertyKey: string
  valueJson: string
  onChange: (patch: Partial<Props>) => void
}

export function ZwavejsSetValueActionFields({ nodeId, commandClass, endpoint, property, propertyKey, valueJson, onChange }: Props) {
  return (
    <>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Node ID <HelpTip className="ml-1" content="Z-Wave node id (integer)." />
        </label>
        <Input value={nodeId} onChange={(e) => onChange({ nodeId: e.target.value })} placeholder="e.g., 12" />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Command Class <HelpTip className="ml-1" content="ValueID.commandClass (integer)." />
        </label>
        <Input value={commandClass} onChange={(e) => onChange({ commandClass: e.target.value })} placeholder="e.g., 37" />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Endpoint <HelpTip className="ml-1" content="ValueID.endpoint (default 0)." />
        </label>
        <Input value={endpoint} onChange={(e) => onChange({ endpoint: e.target.value })} placeholder="0" />
      </div>
      <div className="grid gap-3 md:col-span-3 md:grid-cols-3">
        <div className="space-y-1 md:col-span-2">
          <label className="text-xs text-muted-foreground">
            Property <HelpTip className="ml-1" content="ValueID.property (string or number)." />
          </label>
          <Input value={property} onChange={(e) => onChange({ property: e.target.value })} placeholder="e.g., targetValue" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Property Key (optional) <HelpTip className="ml-1" content="ValueID.propertyKey (string or number)." />
          </label>
          <Input value={propertyKey} onChange={(e) => onChange({ propertyKey: e.target.value })} placeholder="e.g., 1" />
        </div>
      </div>
      <div className="space-y-1 md:col-span-3">
        <label className="text-xs text-muted-foreground">
          Value (JSON) <HelpTip className="ml-1" content="The value to set (JSON)." />
        </label>
        <Textarea
          className="min-h-[96px] font-mono text-xs"
          value={valueJson}
          onChange={(e) => onChange({ valueJson: e.target.value })}
          spellCheck={false}
        />
      </div>
    </>
  )
}

