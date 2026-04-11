import { Radio } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import { IntegrationSettingsForm } from '@/features/integrations/components/IntegrationSettingsForm'
import { useSettingsRegistryEntry } from '@/hooks/useSettingsRegistry'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  values: Record<string, unknown> | null
  maskedFlags: Record<string, boolean>
  isLoading: boolean
  connected: boolean | undefined
  enabled: boolean | undefined
  lastError: string | null | undefined
  saveDisabled: boolean
  onRefresh: () => void
  onSave: () => void
  onSync: () => void
  onChange: (key: string, value: unknown) => void
}

export function ZwavejsSettingsCard({
  isAdmin,
  isBusy,
  values,
  maskedFlags,
  isLoading,
  connected,
  enabled,
  lastError,
  saveDisabled,
  onRefresh,
  onSave,
  onSync,
  onChange,
}: Props) {
  const registryEntry = useSettingsRegistryEntry('zwavejs')

  return (
    <div className="space-y-3 sm:space-y-4">
      <IntegrationOverviewCard
        title={
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4" />
            <span>Z-Wave JS</span>
          </div>
        }
        description="Connect to Z-Wave JS UI / zwave-js-server via WebSocket."
        isAdmin={isAdmin}
        isBusy={isBusy}
        status={{ connected, enabled, lastError }}
        enableLabel="Enable Z-Wave JS"
        enabled={Boolean(values?.enabled)}
        onEnabledChange={(checked) => onChange('enabled', checked)}
        onRefresh={onRefresh}
        onSave={onSave}
        saveDisabled={saveDisabled}
        opsActions={
          <Button type="button" variant="outline" onClick={onSync} disabled={!isAdmin || isBusy || !values}>
            Sync Entities
          </Button>
        }
      >
        {isLoading && !values ? <LoadingInline /> : !values ? <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div> : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard description="Configure Z-Wave JS WebSocket connection and operational settings.">
        {isLoading && !values ? (
          <LoadingInline />
        ) : !values || !registryEntry.data ? (
          <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div>
        ) : (
          <IntegrationSettingsForm
            schema={registryEntry.data.configSchema}
            encryptedFields={registryEntry.data.encryptedFields}
            values={values}
            maskedFlags={maskedFlags}
            disabled={!isAdmin}
            onChange={onChange}
          />
        )}
      </IntegrationConnectionCard>
    </div>
  )
}
