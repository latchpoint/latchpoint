import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { SectionCard } from '@/components/ui/section-card'
import { Switch } from '@/components/ui/switch'
import { BooleanStatusPill } from '@/features/integrations/components/BooleanStatusPill'
import type { HaMqttEntityDraft } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'

type Props = {
  isAdmin: boolean
  mqttReady: boolean
  draft: HaMqttEntityDraft | null
  status: { lastDiscoveryPublishAt?: string | null } | null
  isSaving: boolean
  isPublishing: boolean
  onSetDraft: (updater: (prev: HaMqttEntityDraft | null) => HaMqttEntityDraft | null) => void
  onSave: () => void
  onPublishDiscovery: () => void
  onRefresh: () => void
}

export function HomeAssistantMqttAlarmEntityCard({
  isAdmin,
  mqttReady,
  draft,
  status,
  isSaving,
  isPublishing,
  onSetDraft,
  onSave,
  onPublishDiscovery,
  onRefresh,
}: Props) {
  return (
    <SectionCard
      title="Home Assistant: MQTT Alarm Entity"
      description="Expose the alarm as an alarm_control_panel via Home Assistant MQTT discovery (requires MQTT enabled)."
    >
      {!mqttReady ? (
        <Alert variant="warning">
          <AlertDescription>
            Enable and configure MQTT first (Settings → MQTT). The Home Assistant MQTT alarm entity cannot be enabled without MQTT.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <span>Enable alarm entity</span>
            <HelpTip content="Publishes a Home Assistant MQTT alarm_control_panel entity via discovery (requires MQTT enabled/configured)." />
          </div>
          <Switch
            checked={draft?.enabled ?? false}
            onCheckedChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, enabled: checked } : prev))}
            disabled={!isAdmin || !mqttReady || isSaving}
          />
        </div>

        <FormField label="Entity name" htmlFor="haMqttEntityName" help="Display name shown in Home Assistant for the MQTT alarm control panel entity." required>
          <Input
            id="haMqttEntityName"
            value={draft?.entityName ?? ''}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, entityName: e.target.value } : prev))}
            disabled={!isAdmin || !mqttReady || isSaving || !(draft?.enabled ?? false)}
          />
        </FormField>

        <FormField label="Home Assistant entity id" htmlFor="haMqttEntityId" help="Optional custom entity_id to use in Home Assistant (defaults to alarm_control_panel.latchpoint_alarm).">
          <Input
            id="haMqttEntityId"
            value={draft?.haEntityId ?? ''}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, haEntityId: e.target.value } : prev))}
            disabled={!isAdmin || !mqttReady || isSaving || !(draft?.enabled ?? false)}
          />
        </FormField>

        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft?.alsoRenameInHomeAssistant ?? true}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, alsoRenameInHomeAssistant: e.target.checked } : prev))}
            disabled={!isAdmin || !mqttReady || isSaving || !(draft?.enabled ?? false)}
          />
          <span className="flex items-center gap-2">
            <span>Republishes discovery on rename</span>
            <HelpTip content="When enabled, changing the entity name/id will republish MQTT discovery so Home Assistant updates the entity." />
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Discovery:</span>
          <BooleanStatusPill
            value={Boolean(status?.lastDiscoveryPublishAt)}
            trueLabel="Published"
            falseLabel="Not published"
            trueVariant="default"
            falseVariant="default"
            trueClassName="text-success"
            falseClassName="text-muted-foreground"
          />
          {status?.lastDiscoveryPublishAt ? <span className="text-muted-foreground">({new Date(status.lastDiscoveryPublishAt).toLocaleString()})</span> : null}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant="outline" disabled={!isAdmin || !mqttReady || !draft || isSaving} onClick={onSave}>
            Save alarm entity
          </Button>

          <Button type="button" variant="secondary" disabled={!isAdmin || !mqttReady || isPublishing || !(draft?.enabled ?? false)} onClick={onPublishDiscovery}>
            Publish discovery
          </Button>

          <Button type="button" variant="ghost" onClick={onRefresh}>
            Refresh
          </Button>
        </div>
      </div>
    </SectionCard>
  )
}

