import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { RuleKind } from '@/types'

type Props = {
  ruleKinds: { value: RuleKind; label: string }[]
  name: string
  setName: (next: string) => void
  kind: RuleKind
  setKind: (next: RuleKind) => void
  enabled: boolean
  setEnabled: (next: boolean) => void
  priority: number
  setPriority: (next: number) => void
  advanced: boolean
  onToggleAdvanced: () => void
}

export function RuleMetaFields({
  ruleKinds,
  name,
  setName,
  kind,
  setKind,
  enabled,
  setEnabled,
  priority,
  setPriority,
  advanced,
  onToggleAdvanced,
}: Props) {
  return (
    <>
      <div className="grid gap-3 md:grid-cols-2">
        <FormField size="compact" label="Name" htmlFor="rule-name" help="A human-friendly label for the rule.">
          <Input id="rule-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., Disarm if presence for 5m" />
        </FormField>

        <div className="grid grid-cols-2 gap-3">
          <FormField
            size="compact"
            label="Kind"
            htmlFor="rule-kind"
            help="What category the rule belongs to (trigger/disarm/arm/etc.). This is used for filtering and later conflict policy."
          >
            <Select id="rule-kind" size="sm" value={kind} onChange={(e) => setKind(e.target.value as RuleKind)}>
              {ruleKinds.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          </FormField>

          <FormField size="compact" label="Priority" htmlFor="rule-priority" help="Higher priority rules are evaluated first (and may win if multiple rules match).">
            <Input id="rule-priority" value={String(priority)} onChange={(e) => setPriority(Number.parseInt(e.target.value || '0', 10) || 0)} />
          </FormField>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-labelledby="rule-enabled-label" />
            <span id="rule-enabled-label" className="text-sm">
              Enabled
            </span>
          </div>
          <HelpTip content="Disabled rules are saved but ignored by the engine." />
        </div>
        <Button type="button" variant="outline" onClick={onToggleAdvanced}>
          {advanced ? 'Use Builder' : 'Advanced JSON'}
        </Button>
      </div>
    </>
  )
}

