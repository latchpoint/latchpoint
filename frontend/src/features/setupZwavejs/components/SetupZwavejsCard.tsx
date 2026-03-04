import { Radio } from 'lucide-react'
import type { FieldErrors, UseFormHandleSubmit, UseFormRegister, UseFormSetValue, UseFormWatch } from 'react-hook-form'
import { CenteredCard } from '@/components/ui/centered-card'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AdminActionRequiredAlert } from '@/features/settings/components/AdminActionRequiredAlert'
import { ConnectionStatusTextBlock } from '@/features/integrations/components/ConnectionStatus'
import type { SetupZwavejsFormData } from '@/features/setupZwavejs/hooks/useSetupZwavejsModel'

type Props = {
  isAdmin: boolean
  error: string | null
  notice: string | null
  isBusy: boolean
  isSubmitting: boolean
  isTesting: boolean
  isSyncing: boolean
  connected: boolean | undefined
  integrationEnabled: boolean | undefined
  lastError: string | undefined
  formErrors: FieldErrors<SetupZwavejsFormData>
  register: UseFormRegister<SetupZwavejsFormData>
  handleSubmit: UseFormHandleSubmit<SetupZwavejsFormData>
  watch: UseFormWatch<SetupZwavejsFormData>
  setValue: UseFormSetValue<SetupZwavejsFormData>
  onSync: () => Promise<void>
  onBackToSettings: () => void
}

export function SetupZwavejsCard({
  isAdmin,
  error,
  notice,
  isBusy,
  isSyncing,
  connected,
  integrationEnabled,
  lastError,
  watch,
  onSync,
  onBackToSettings,
}: Props) {
  const enabled = watch('enabled')
  const wsUrl = watch('wsUrl')
  const connectTimeoutSeconds = watch('connectTimeoutSeconds')
  const reconnectMinSeconds = watch('reconnectMinSeconds')
  const reconnectMaxSeconds = watch('reconnectMaxSeconds')

  return (
    <CenteredCard
      layout="section"
      title="Z-Wave JS"
      description="Z-Wave JS connection is configured via environment variables."
      icon={<Radio className="h-6 w-6" />}
    >
      {!isAdmin ? <AdminActionRequiredAlert description="An admin must configure Z-Wave JS integration." /> : null}

      <ConnectionStatusTextBlock connected={connected} enabled={integrationEnabled} lastError={lastError} />

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <span className="text-muted-foreground">Enabled</span>
          <span>{enabled ? 'Yes' : 'No'}</span>

          <span className="text-muted-foreground">WebSocket URL</span>
          <span className="break-all">{wsUrl || '(not set)'}</span>

          <span className="text-muted-foreground">Connect timeout</span>
          <span>{connectTimeoutSeconds}s</span>

          <span className="text-muted-foreground">Reconnect min</span>
          <span>{reconnectMinSeconds}s</span>

          <span className="text-muted-foreground">Reconnect max</span>
          <span>{reconnectMaxSeconds}s</span>
        </div>

        {error ? (
          <Alert variant="error" layout="inline">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : notice ? (
          <Alert layout="inline">
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant="outline" className="flex-1" onClick={() => void onSync()} disabled={!isAdmin || isBusy || isSyncing}>
            {isSyncing ? 'Syncing...' : 'Sync Entities'}
          </Button>
        </div>

        <Button type="button" className="w-full" variant="ghost" onClick={onBackToSettings}>
          Back to settings
        </Button>
      </div>
    </CenteredCard>
  )
}
