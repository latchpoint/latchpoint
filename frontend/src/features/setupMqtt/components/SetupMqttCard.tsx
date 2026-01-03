import { Wifi } from 'lucide-react'
import { CenteredCard } from '@/components/ui/centered-card'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Checkbox } from '@/components/ui/checkbox'
import { Switch } from '@/components/ui/switch'
import { AdminActionRequiredAlert } from '@/features/settings/components/AdminActionRequiredAlert'
import { ConnectionStatusTextBlock } from '@/features/integrations/components/ConnectionStatus'
import type { SetupMqttFormData } from '@/features/setupMqtt/hooks/useSetupMqttModel'
import type { FieldErrors, UseFormHandleSubmit, UseFormRegister, UseFormSetValue, UseFormWatch } from 'react-hook-form'

type Props = {
  isAdmin: boolean
  error: string | null
  notice: string | null
  hasSavedPassword: boolean
  passwordFieldValue: string
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
  onSubmit: (data: SetupMqttFormData) => Promise<void>
  onTest: () => Promise<void>
  onClearPassword: () => Promise<void>
  onBackToSettings: () => void
}

export function SetupMqttCard({
  isAdmin,
  error,
  notice,
  hasSavedPassword,
  passwordFieldValue,
  isBusy,
  isSubmitting,
  isTesting,
  connected,
  lastError,
  formErrors,
  register,
  handleSubmit,
  watch,
  setValue,
  onSubmit,
  onTest,
  onClearPassword,
  onBackToSettings,
}: Props) {
  const enabled = watch('enabled')

  return (
    <CenteredCard
      layout="section"
      title="MQTT"
      description="Connect to an MQTT broker for integrations (Home Assistant, Zigbee2MQTT, and more)."
      icon={<Wifi className="h-6 w-6" />}
    >
      {!isAdmin ? <AdminActionRequiredAlert description="An admin must configure MQTT." /> : null}

      <ConnectionStatusTextBlock connected={connected} lastError={lastError} />

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="text-sm font-medium">Enable MQTT integration</div>
          <Switch checked={enabled} onCheckedChange={(checked) => setValue('enabled', checked)} disabled={!isAdmin || isBusy} />
        </div>

        <FormField label="Broker host" htmlFor="host" required>
          <Input id="host" placeholder="localhost" {...register('host')} disabled={!isAdmin || isBusy} />
        </FormField>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="Port" htmlFor="port" required error={formErrors.port?.message}>
            <Input id="port" inputMode="numeric" {...register('port')} disabled={!isAdmin || isBusy} />
          </FormField>

          <FormField label="Client ID" htmlFor="clientId" required error={formErrors.clientId?.message}>
            <Input id="clientId" placeholder="latchpoint-alarm" {...register('clientId')} disabled={!isAdmin || isBusy} />
          </FormField>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="Username" htmlFor="username">
            <Input id="username" {...register('username')} disabled={!isAdmin || isBusy} />
          </FormField>

          <FormField label="Password" htmlFor="password">
            <Input id="password" type="password" {...register('password')} disabled={!isAdmin || isBusy} />
            {hasSavedPassword && !passwordFieldValue ? (
              <div className="mt-1 text-xs text-muted-foreground">Password is saved (not shown). Leave blank to keep it.</div>
            ) : null}
            {hasSavedPassword ? (
              <div className="mt-2">
                <Button type="button" size="sm" variant="destructive" disabled={!isAdmin || isBusy} onClick={() => void onClearPassword()}>
                  Clear password
                </Button>
              </div>
            ) : null}
          </FormField>
        </div>

        <div className="flex items-center gap-2">
          <Checkbox checked={watch('useTls')} onChange={(e) => setValue('useTls', e.target.checked)} disabled={!isAdmin || isBusy} />
          <span className="text-sm">Use TLS</span>
        </div>

        {watch('useTls') ? (
          <div className="flex items-center gap-2">
            <Checkbox checked={watch('tlsInsecure')} onChange={(e) => setValue('tlsInsecure', e.target.checked)} disabled={!isAdmin || isBusy} />
            <span className="text-sm">Allow insecure TLS (skip cert verification)</span>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="Keepalive (seconds)" htmlFor="keepaliveSeconds" required error={formErrors.keepaliveSeconds?.message}>
            <Input id="keepaliveSeconds" inputMode="numeric" {...register('keepaliveSeconds')} disabled={!isAdmin || isBusy} />
          </FormField>
          <FormField label="Connect timeout (seconds)" htmlFor="connectTimeoutSeconds" required error={formErrors.connectTimeoutSeconds?.message}>
            <Input id="connectTimeoutSeconds" inputMode="decimal" {...register('connectTimeoutSeconds')} disabled={!isAdmin || isBusy} />
          </FormField>
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

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="submit" className="w-full" disabled={!isAdmin || isBusy}>
            {isSubmitting ? 'Saving…' : 'Save'}
          </Button>
          <Button type="button" className="w-full" variant="outline" onClick={() => void onTest()} disabled={!isAdmin || isBusy || isTesting}>
            {isTesting ? 'Testing…' : 'Test Connection'}
          </Button>
        </div>

        <Button type="button" className="w-full" variant="ghost" onClick={onBackToSettings}>
          Back to settings
        </Button>
      </form>
    </CenteredCard>
  )
}
