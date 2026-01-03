import { Alert, AlertDescription } from '@/components/ui/alert'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { Zigbee2mqttDraft } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  mqttReady: boolean
  draft: Zigbee2mqttDraft
  onUpdateDraft: (patch: Partial<Zigbee2mqttDraft>) => void
  onSetError: (msg: string | null) => void
}

export function Zigbee2mqttEnableSection({ isAdmin, isBusy, mqttReady, draft, onUpdateDraft, onSetError }: Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium">
            Enable Zigbee2MQTT
            <HelpTip className="ml-1" content="Requires MQTT to be enabled first (Settings → MQTT)." />
          </div>
          <div className="text-sm text-muted-foreground">Requires MQTT broker enabled and connected.</div>
        </div>
        <Switch
          checked={draft.enabled}
          onCheckedChange={(checked) => {
            if (checked && !mqttReady) {
              onSetError('Enable MQTT first (Settings → MQTT) before enabling Zigbee2MQTT.')
              return
            }
            onUpdateDraft({ enabled: checked })
          }}
          disabled={!isAdmin || isBusy || (!draft.enabled && !mqttReady)}
        />
      </div>

      {!mqttReady ? (
        <Alert variant="warning">
          <AlertDescription>
            {draft.enabled
              ? 'Zigbee2MQTT is enabled, but MQTT is disabled. Zigbee2MQTT events will not be ingested until MQTT is enabled in Settings → MQTT.'
              : 'MQTT is not enabled/configured. Enable MQTT in Settings → MQTT before enabling Zigbee2MQTT.'}
          </AlertDescription>
        </Alert>
      ) : null}

      <FormField label="Base topic" htmlFor="z2mBaseTopic" help="Zigbee2MQTT base topic (default: zigbee2mqtt).">
        <Input
          id="z2mBaseTopic"
          value={draft.baseTopic}
          onChange={(e) => onUpdateDraft({ baseTopic: e.target.value })}
          placeholder="zigbee2mqtt"
          disabled={!isAdmin || isBusy}
        />
      </FormField>
    </div>
  )
}

