import { Radio } from 'lucide-react'
import type { FieldErrors, UseFormHandleSubmit, UseFormRegister, UseFormSetValue, UseFormWatch } from 'react-hook-form'
import { CenteredCard } from '@/components/ui/centered-card'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Switch } from '@/components/ui/switch'
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
  onSubmit: (data: SetupZwavejsFormData) => Promise<void>
  onTest: () => Promise<void>
  onSync: () => Promise<void>
  onBackToSettings: () => void
}

export function SetupZwavejsCard({
  isAdmin,
  error,
  notice,
  isBusy,
  isSubmitting,
  isTesting,
  isSyncing,
  connected,
  integrationEnabled,
  lastError,
  formErrors,
  register,
  handleSubmit,
  watch,
  setValue,
  onSubmit,
  onTest,
  onSync,
  onBackToSettings,
}: Props) {
  const enabled = watch('enabled')

  return (
    <CenteredCard
      layout="section"
      title="Z-Wave JS"
      description="Connect to Z-Wave JS UI / zwave-js-server via WebSocket."
      icon={<Radio className="h-6 w-6" />}
    >
      {!isAdmin ? <AdminActionRequiredAlert description="An admin must configure Z-Wave JS integration." /> : null}

      <ConnectionStatusTextBlock connected={connected} enabled={integrationEnabled} lastError={lastError} />

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="text-sm font-medium">Enable Z-Wave JS integration</div>
          <Switch checked={enabled} onCheckedChange={(checked) => setValue('enabled', checked)} disabled={!isAdmin || isBusy} />
        </div>

        <FormField label="WebSocket URL" htmlFor="wsUrl" required error={formErrors.wsUrl?.message}>
          <Input id="wsUrl" placeholder="ws://localhost:3000" {...register('wsUrl')} disabled={!isAdmin || isBusy} />
          <div className="mt-1 text-xs text-muted-foreground">Z-Wave JS UI / zwave-js-server commonly uses WS port 3000.</div>
        </FormField>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField label="Connect timeout (s)" htmlFor="connectTimeoutSeconds" required error={formErrors.connectTimeoutSeconds?.message}>
            <Input id="connectTimeoutSeconds" inputMode="decimal" {...register('connectTimeoutSeconds')} disabled={!isAdmin || isBusy} />
          </FormField>
          <FormField label="Reconnect min (s)" htmlFor="reconnectMinSeconds" required error={formErrors.reconnectMinSeconds?.message}>
            <Input id="reconnectMinSeconds" inputMode="numeric" {...register('reconnectMinSeconds')} disabled={!isAdmin || isBusy} />
          </FormField>
          <FormField label="Reconnect max (s)" htmlFor="reconnectMaxSeconds" required error={formErrors.reconnectMaxSeconds?.message}>
            <Input id="reconnectMaxSeconds" inputMode="numeric" {...register('reconnectMaxSeconds')} disabled={!isAdmin || isBusy} />
          </FormField>
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
          <Button type="submit" className="flex-1" disabled={!isAdmin || isBusy}>
            {isSubmitting ? 'Saving…' : 'Save'}
          </Button>
          <Button type="button" variant="secondary" className="flex-1" onClick={() => void onTest()} disabled={!isAdmin || isBusy || isTesting}>
            {isTesting ? 'Testing…' : 'Test Connection'}
          </Button>
          <Button type="button" variant="outline" className="flex-1" onClick={() => void onSync()} disabled={!isAdmin || isBusy || isSyncing}>
            {isSyncing ? 'Syncing…' : 'Sync Entities'}
          </Button>
        </div>

        <Button type="button" className="w-full" variant="ghost" onClick={onBackToSettings}>
          Back to settings
        </Button>
      </form>
    </CenteredCard>
  )
}
