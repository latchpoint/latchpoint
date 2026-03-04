import { Wifi } from 'lucide-react'
import { CenteredCard } from '@/components/ui/centered-card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { AdminActionRequiredAlert } from '@/features/settings/components/AdminActionRequiredAlert'
import { ConnectionStatusTextBlock } from '@/features/integrations/components/ConnectionStatus'
import type { SetupMqttFormData } from '@/features/setupMqtt/hooks/useSetupMqttModel'
import type { FieldErrors, UseFormHandleSubmit, UseFormRegister, UseFormSetValue, UseFormWatch } from 'react-hook-form'

type Props = {
  isAdmin: boolean
  error: string | null
  notice: string | null
  hasSavedPassword: boolean
  isBusy: boolean
  isSubmitting: boolean
  isTesting: boolean
  connected: boolean | undefined
  lastError: string | undefined
  formErrors: FieldErrors<SetupMqttFormData>
  register: UseFormRegister<SetupMqttFormData>
  handleSubmit: UseFormHandleSubmit<SetupMqttFormData>
  watch: UseFormWatch<SetupMqttFormData>
  setValue: UseFormSetValue<SetupMqttFormData>
  onBackToSettings: () => void
}

export function SetupMqttCard({
  isAdmin,
  error,
  notice,
  hasSavedPassword,
  connected,
  lastError,
  watch,
  onBackToSettings,
}: Props) {
  const enabled = watch('enabled')
  const host = watch('host')
  const port = watch('port')
  const clientId = watch('clientId')
  const username = watch('username')
  const useTls = watch('useTls')
  const tlsInsecure = watch('tlsInsecure')
  const keepaliveSeconds = watch('keepaliveSeconds')
  const connectTimeoutSeconds = watch('connectTimeoutSeconds')

  return (
    <CenteredCard
      layout="section"
      title="MQTT"
      description="MQTT broker connection is configured via environment variables."
      icon={<Wifi className="h-6 w-6" />}
    >
      {!isAdmin ? <AdminActionRequiredAlert description="An admin must configure MQTT." /> : null}

      <ConnectionStatusTextBlock connected={connected} lastError={lastError} />

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <span className="text-muted-foreground">Enabled</span>
          <span>{enabled ? 'Yes' : 'No'}</span>

          <span className="text-muted-foreground">Broker host</span>
          <span className="break-all">{host || '(not set)'}</span>

          <span className="text-muted-foreground">Port</span>
          <span>{port}</span>

          <span className="text-muted-foreground">Client ID</span>
          <span>{clientId || '(not set)'}</span>

          <span className="text-muted-foreground">Username</span>
          <span>{username || '(not set)'}</span>

          <span className="text-muted-foreground">Password</span>
          <span>{hasSavedPassword ? 'Configured' : 'Not set'}</span>

          <span className="text-muted-foreground">TLS</span>
          <span>{useTls ? 'Yes' : 'No'}{useTls && tlsInsecure ? ' (insecure)' : ''}</span>

          <span className="text-muted-foreground">Keepalive</span>
          <span>{keepaliveSeconds}s</span>

          <span className="text-muted-foreground">Connect timeout</span>
          <span>{connectTimeoutSeconds}s</span>
        </div>

        {error ? (
          <Alert variant="error" layout="inline">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {notice ? (
          <Alert variant="success" layout="inline">
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        ) : null}

        <Button type="button" className="w-full" variant="ghost" onClick={onBackToSettings}>
          Back to settings
        </Button>
      </div>
    </CenteredCard>
  )
}
