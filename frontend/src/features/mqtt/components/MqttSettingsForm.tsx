import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationSettingsForm } from '@/features/integrations/components/IntegrationSettingsForm'
import { useSettingsRegistryEntry } from '@/hooks/useSettingsRegistry'

type Props = {
  values: Record<string, unknown> | null
  maskedFlags: Record<string, boolean>
  isLoading: boolean
  isAdmin: boolean
  onChange: (key: string, value: unknown) => void
}

export function MqttSettingsForm({
  values,
  maskedFlags,
  isLoading,
  isAdmin,
  onChange,
}: Props) {
  const registryEntry = useSettingsRegistryEntry('mqtt')

  if (isLoading && !values) return <LoadingInline />
  if (!values || !registryEntry.data) return <div className="text-sm text-muted-foreground">MQTT settings unavailable.</div>

  return (
    <IntegrationSettingsForm
      schema={registryEntry.data.configSchema}
      encryptedFields={registryEntry.data.encryptedFields}
      values={values}
      maskedFlags={maskedFlags}
      disabled={!isAdmin}
      onChange={onChange}
    />
  )
}
