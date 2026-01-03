import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { Zigbee2mqttDraft } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  draft: Zigbee2mqttDraft
  onUpdateDraft: (patch: Partial<Zigbee2mqttDraft>) => void
}

export function Zigbee2mqttRulesAndPanelSection({
  isAdmin,
  isBusy,
  draft,
  onUpdateDraft,
}: Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 rounded-md border border-border p-3">
        <div>
          <div className="text-sm font-medium">
            Run rules on Zigbee2MQTT events
            <HelpTip className="ml-1" content="When enabled, Zigbee2MQTT ingest will trigger debounced rule evaluation." />
          </div>
          <div className="text-xs text-muted-foreground">Off by default (Z2M can be chatty).</div>
        </div>
        <Switch checked={draft.runRulesOnEvent} onCheckedChange={(checked) => onUpdateDraft({ runRulesOnEvent: checked })} disabled={!isAdmin || isBusy} />
      </div>

      <FormField
        label="Rules debounce (seconds)"
        htmlFor="z2mRunRulesDebounceSeconds"
        help="Minimum seconds between automatic rule evaluations triggered by Z2M ingest."
      >
        <Input
          id="z2mRunRulesDebounceSeconds"
          value={draft.runRulesDebounceSeconds}
          onChange={(e) => onUpdateDraft({ runRulesDebounceSeconds: e.target.value })}
          disabled={!isAdmin || isBusy}
        />
      </FormField>

      <FormField
        label="Rules max per minute"
        htmlFor="z2mRunRulesMaxPerMinute"
        help="Backpressure: maximum automatic rule evaluations per minute (0 disables rate limit)."
      >
        <Input
          id="z2mRunRulesMaxPerMinute"
          value={draft.runRulesMaxPerMinute}
          onChange={(e) => onUpdateDraft({ runRulesMaxPerMinute: e.target.value })}
          disabled={!isAdmin || isBusy}
        />
      </FormField>

      <FormField
        label="Auto-run rule kinds"
        htmlFor="z2mRunRulesKinds"
        help="Comma-separated rule kinds to evaluate on Z2M ingest (default: trigger)."
      >
        <Input
          id="z2mRunRulesKinds"
          value={draft.runRulesKindsCsv}
          onChange={(e) => onUpdateDraft({ runRulesKindsCsv: e.target.value })}
          placeholder="trigger"
          disabled={!isAdmin || isBusy}
        />
      </FormField>
    </div>
  )
}
