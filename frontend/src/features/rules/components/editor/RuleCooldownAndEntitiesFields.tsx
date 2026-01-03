import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type Props = {
  advanced: boolean
  cooldownSeconds: string
  setCooldownSeconds: (next: string) => void
  entitiesLength: number
  entityIdsText: string
  setEntityIdsText: (next: string) => void
  derivedEntityIds: string[]
  derivedEntityIdsText: string
}

export function RuleCooldownAndEntitiesFields({
  advanced,
  cooldownSeconds,
  setCooldownSeconds,
  entitiesLength,
  entityIdsText,
  setEntityIdsText,
  derivedEntityIds,
  derivedEntityIdsText,
}: Props) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <FormField
        size="compact"
        label="Cooldown seconds (optional)"
        htmlFor="rule-cooldown-seconds"
        help="Minimum time between fires for this rule (helps prevent spam/flapping)."
      >
        <Input id="rule-cooldown-seconds" value={cooldownSeconds} onChange={(e) => setCooldownSeconds(e.target.value)} placeholder="e.g., 60" />
      </FormField>

      <FormField
        size="compact"
        label="Referenced entity IDs"
        htmlFor="rule-entity-ids"
        help="Used to quickly find which rules should re-evaluate when an entity changes. In Builder mode this is derived from your conditions; in Advanced mode you can edit it."
        description={!advanced ? `Auto-derived from conditions: ${derivedEntityIds.length ? derivedEntityIds.join(', ') : '—'}` : `Known entities: ${entitiesLength}.`}
      >
        <Textarea
          id="rule-entity-ids"
          className="min-h-[88px]"
          value={advanced ? entityIdsText : derivedEntityIdsText}
          onChange={(e) => setEntityIdsText(e.target.value)}
          placeholder="One per line (or comma-separated)"
          disabled={!advanced}
        />
      </FormField>
    </div>
  )
}

