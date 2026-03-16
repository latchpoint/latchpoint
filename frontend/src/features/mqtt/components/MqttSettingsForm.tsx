import { LoadingInline } from '@/components/ui/loading-inline'
import type { MqttDraft } from '@/features/mqtt/hooks/useMqttSettingsModel'

type Props = {
  draft: MqttDraft | null
  isLoading: boolean
}

export function MqttSettingsForm({
  draft,
  isLoading,
}: Props) {
  if (isLoading && !draft) return <LoadingInline />
  if (!draft) return <div className="text-sm text-muted-foreground">MQTT settings unavailable.</div>

  return (
    <div className="grid grid-cols-2 gap-2 text-sm">
      <span className="text-muted-foreground">Enabled</span>
      <span>{draft.enabled ? 'Yes' : 'No'}</span>

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

      <span className="text-muted-foreground">Keepalive</span>
      <span>{draft.keepaliveSeconds}s</span>

      <span className="text-muted-foreground">Connect timeout</span>
      <span>{draft.connectTimeoutSeconds}s</span>
    </div>
  )
}
