import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationSettingsForm } from '@/features/integrations/components/IntegrationSettingsForm'
import { useSettingsRegistryEntry } from '@/hooks/useSettingsRegistry'
import { getErrorMessage } from '@/types/errors'

type Props = {
  isAdmin: boolean
  values: Record<string, unknown> | null
  maskedFlags: Record<string, boolean>
  isLoading: boolean
  isError: boolean
  loadError: unknown
  onChange: (key: string, value: unknown) => void
}

export function HomeAssistantConnectionCard({
  isAdmin,
  values,
  maskedFlags,
  isLoading,
  isError,
  loadError,
  onChange,
}: Props) {
  const registryEntry = useSettingsRegistryEntry('home_assistant')

  return (
    <IntegrationConnectionCard
      title="Connection / setup"
      description="Configure the Home Assistant connection URL, access token, and operational settings."
    >
      <div className="space-y-3">
        {values && registryEntry.data ? (
          <IntegrationSettingsForm
            schema={registryEntry.data.configSchema}
            encryptedFields={registryEntry.data.encryptedFields}
            values={values}
            maskedFlags={maskedFlags}
            disabled={!isAdmin}
            onChange={onChange}
          />
        ) : !isAdmin ? (
          <div className="text-sm text-muted-foreground">Only admins can view Home Assistant settings.</div>
        ) : isError ? (
          <Alert variant="error">
            <AlertDescription>{getErrorMessage(loadError) || 'Failed to load Home Assistant settings.'}</AlertDescription>
          </Alert>
        ) : isLoading ? (
          <LoadingInline />
        ) : (
          <div className="text-sm text-muted-foreground">Home Assistant settings unavailable.</div>
        )}
      </div>
    </IntegrationConnectionCard>
  )
}
