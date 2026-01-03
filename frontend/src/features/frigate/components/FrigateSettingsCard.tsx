import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import type { FrigateDraft } from '@/features/frigate/hooks/useFrigateSettingsModel'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  draft: FrigateDraft | null
  isLoading: boolean
  onSetDraft: (updater: (prev: FrigateDraft | null) => FrigateDraft | null) => void
}

export function FrigateSettingsCard({ isAdmin, isBusy, draft, isLoading, onSetDraft }: Props) {
  return (
    <IntegrationConnectionCard title="Setup / settings" description="Configure the MQTT topic and retention used for ingest.">
      {!isAdmin ? (
        <div className="text-sm text-muted-foreground">Only admins can view and edit Frigate settings.</div>
      ) : isLoading || !draft ? (
        <LoadingInline label="Loading Frigate settings…" />
      ) : (
        <div className="space-y-4">
          <FormField label="Events topic" htmlFor="frigateEventsTopic" help="MQTT topic to subscribe to for Frigate events (default: frigate/events).">
            <Input id="frigateEventsTopic" value={draft.eventsTopic} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, eventsTopic: e.target.value } : prev))} placeholder="frigate/events" disabled={isBusy} />
          </FormField>

          <FormField label="Retention (seconds)" htmlFor="frigateRetentionSeconds" help="How long to keep ingested detections for rule evaluation.">
            <Input id="frigateRetentionSeconds" value={draft.retentionSeconds} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, retentionSeconds: e.target.value } : prev))} disabled={isBusy} />
          </FormField>

          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <div className="text-sm font-medium">
                Run rules on Frigate events
                <HelpTip className="ml-1" content="When enabled, ingested person events will trigger a debounced rules evaluation." />
              </div>
              <div className="text-xs text-muted-foreground">Useful to make Frigate-driven rules feel real-time.</div>
            </div>
            <Switch checked={draft.runRulesOnEvent} onCheckedChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, runRulesOnEvent: checked } : prev))} disabled={isBusy} />
          </div>

          <FormField label="Rules debounce (seconds)" htmlFor="frigateRunRulesDebounceSeconds" help="Minimum seconds between automatic rule evaluations triggered by Frigate ingest.">
            <Input id="frigateRunRulesDebounceSeconds" value={draft.runRulesDebounceSeconds} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, runRulesDebounceSeconds: e.target.value } : prev))} disabled={isBusy} />
          </FormField>

          <FormField label="Rules max per minute" htmlFor="frigateRunRulesMaxPerMinute" help="Backpressure: maximum automatic rule evaluations per minute (0 disables rate limit).">
            <Input id="frigateRunRulesMaxPerMinute" value={draft.runRulesMaxPerMinute} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, runRulesMaxPerMinute: e.target.value } : prev))} disabled={isBusy} />
          </FormField>

          <FormField label="Auto-run rule kinds" htmlFor="frigateRunRulesKinds" help="Comma-separated rule kinds to evaluate on Frigate ingest (default: trigger).">
            <Input id="frigateRunRulesKinds" value={draft.runRulesKindsCsv} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, runRulesKindsCsv: e.target.value } : prev))} placeholder="trigger" disabled={isBusy} />
          </FormField>

          <FormField label="Known cameras (optional)" htmlFor="frigateKnownCameras" help="Comma-separated camera names to show in the Rules UI even before any events are ingested.">
            <Input id="frigateKnownCameras" value={draft.knownCamerasCsv} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, knownCamerasCsv: e.target.value } : prev))} placeholder="backyard, porch" disabled={isBusy} />
          </FormField>

          <FormField label="Known zones by camera (optional)" htmlFor="frigateKnownZonesByCamera" help='JSON object mapping camera → zones list (e.g. {"backyard": ["yard","patio"]}).'>
            <Textarea id="frigateKnownZonesByCamera" value={draft.knownZonesByCameraJson} onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, knownZonesByCameraJson: e.target.value } : prev))} className="min-h-[88px]" placeholder='{"backyard":["yard"]}' disabled={isBusy} />
          </FormField>
        </div>
      )}
    </IntegrationConnectionCard>
  )
}
