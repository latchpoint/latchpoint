import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'
import type { MqttDraft } from '@/features/mqtt/hooks/useMqttSettingsModel'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  draft: MqttDraft | null
  isLoading: boolean
  onClearPassword: () => void
  onSetDraft: (updater: (prev: MqttDraft | null) => MqttDraft | null) => void
}

export function MqttSettingsForm({
  isAdmin,
  isBusy,
  draft,
  isLoading,
  onClearPassword,
  onSetDraft,
}: Props) {
  if (isLoading && !draft) return <LoadingInline />
  if (!draft) return <div className="text-sm text-muted-foreground">MQTT settings unavailable.</div>

  return (
    <>
      <FormField label="Broker host" htmlFor="mqttHost" help="MQTT broker hostname or IP (reachable from the backend container)." required={draft.enabled}>
        <Input
          id="mqttHost"
          placeholder="localhost"
          value={draft.host}
          onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, host: e.target.value } : prev))}
          disabled={!isAdmin || isBusy}
        />
      </FormField>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
        <FormField label="Port" htmlFor="mqttPort" help="MQTT broker port (1883 for TCP, 8883 commonly for TLS)." required>
          <Input
            id="mqttPort"
            inputMode="numeric"
            value={draft.port}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, port: e.target.value } : prev))}
            disabled={!isAdmin || isBusy}
          />
        </FormField>

        <FormField label="Client ID" htmlFor="mqttClientId" help="MQTT client identifier for this alarm backend. Must be unique on the broker." required>
          <Input
            id="mqttClientId"
            placeholder="latchpoint-alarm"
            value={draft.clientId}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, clientId: e.target.value } : prev))}
            disabled={!isAdmin || isBusy}
          />
        </FormField>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
        <FormField label="Username" htmlFor="mqttUsername" help="Optional username for broker authentication.">
          <Input
            id="mqttUsername"
            value={draft.username}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, username: e.target.value } : prev))}
            disabled={!isAdmin || isBusy}
          />
        </FormField>

        <FormField
          label="Password"
          htmlFor="mqttPassword"
          help={
            draft.hasPassword && !draft.password
              ? 'A password is already saved. Leave blank to keep it, or enter a new password to replace it.'
              : 'Optional password for broker authentication.'
          }
        >
          <Input
            id="mqttPassword"
            type="password"
            value={draft.password}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, password: e.target.value } : prev))}
            disabled={!isAdmin || isBusy}
          />
          {draft.hasPassword ? (
            <div className="mt-2">
              <Button type="button" size="sm" variant="destructive" onClick={onClearPassword} disabled={!isAdmin || isBusy}>
                Clear password
              </Button>
            </div>
          ) : null}
        </FormField>
      </div>

      <div className="flex items-center gap-2">
        <Checkbox
          checked={draft.useTls}
          onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, useTls: e.target.checked } : prev))}
          disabled={!isAdmin || isBusy}
        />
        <span className="flex items-center gap-2 text-sm">
          <span>Use TLS</span>
          <HelpTip content="Use TLS when connecting to the broker (typically on port 8883)." />
        </span>
      </div>

      {draft.useTls ? (
        <div className="flex items-center gap-2">
          <Checkbox
            checked={draft.tlsInsecure}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, tlsInsecure: e.target.checked } : prev))}
            disabled={!isAdmin || isBusy}
          />
          <span className="flex items-center gap-2 text-sm">
            <span>Allow insecure TLS (skip cert verification)</span>
            <HelpTip content="Disables TLS certificate verification. Use only for local/dev setups with self-signed certs." />
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
        <FormField label="Keepalive (seconds)" htmlFor="mqttKeepalive" help="Keepalive interval sent to the broker; helps detect dropped connections." required>
          <Input
            id="mqttKeepalive"
            inputMode="numeric"
            value={draft.keepaliveSeconds}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, keepaliveSeconds: e.target.value } : prev))}
            disabled={!isAdmin || isBusy}
          />
        </FormField>

        <FormField label="Connect timeout (seconds)" htmlFor="mqttConnectTimeout" help="How long to wait when opening the connection to the broker." required>
          <Input
            id="mqttConnectTimeout"
            inputMode="decimal"
            value={draft.connectTimeoutSeconds}
            onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, connectTimeoutSeconds: e.target.value } : prev))}
            disabled={!isAdmin || isBusy}
          />
        </FormField>
      </div>

    </>
  )
}
