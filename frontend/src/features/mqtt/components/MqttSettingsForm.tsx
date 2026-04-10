import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'
import type { MqttDraft } from '@/features/mqtt/hooks/useMqttSettingsModel'

type Props = {
  draft: MqttDraft | null
  isLoading: boolean
  isAdmin: boolean
  onUpdateDraft: (patch: Partial<MqttDraft>) => void
}

export function MqttSettingsForm({
  draft,
  isLoading,
  isAdmin,
  onUpdateDraft,
}: Props) {
  if (isLoading && !draft) return <LoadingInline />
  if (!draft) return <div className="text-sm text-muted-foreground">MQTT settings unavailable.</div>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 text-sm">
        <span className="text-muted-foreground">Broker host</span>
        <span className="break-all">{draft.host || '(not set)'}</span>

        <span className="text-muted-foreground">Port</span>
        <span>{draft.port}</span>

        <span className="text-muted-foreground">Client ID</span>
        <span>{draft.clientId || '(not set)'}</span>

        <span className="text-muted-foreground">Username</span>
        <span>{draft.username || '(not set)'}</span>

        <span className="text-muted-foreground">Password</span>
        <span>{draft.hasPassword ? 'Configured' : 'Not set'}</span>

        <span className="text-muted-foreground">TLS</span>
        <span>{draft.useTls ? 'Yes' : 'No'}{draft.useTls && draft.tlsInsecure ? ' (insecure)' : ''}</span>
      </div>

      {isAdmin && (
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Keepalive (seconds)" htmlFor="mqtt-keepalive" size="compact">
            <Input
              id="mqtt-keepalive"
              type="number"
              min={1}
              max={3600}
              value={draft.keepaliveSeconds}
              onChange={(e) => onUpdateDraft({ keepaliveSeconds: e.target.value })}
            />
          </FormField>
          <FormField label="Connect timeout (seconds)" htmlFor="mqtt-timeout" size="compact">
            <Input
              id="mqtt-timeout"
              type="number"
              min={1}
              max={300}
              value={draft.connectTimeoutSeconds}
              onChange={(e) => onUpdateDraft({ connectTimeoutSeconds: e.target.value })}
            />
          </FormField>
        </div>
      )}
    </div>
  )
}
