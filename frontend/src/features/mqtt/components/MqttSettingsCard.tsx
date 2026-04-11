import { Wifi } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import { MqttSettingsForm } from '@/features/mqtt/components/MqttSettingsForm'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  values: Record<string, unknown> | null
  maskedFlags: Record<string, boolean>
  isLoading: boolean
  connected: boolean | undefined
  enabled: boolean | undefined
  lastError: string | undefined
  zigbee2mqttEnabled: boolean
  frigateEnabled: boolean
  saveDisabled: boolean
  onRefresh: () => void
  onSave: () => void
  onChange: (key: string, value: unknown) => void
}

export function MqttSettingsCard({
  isAdmin,
  isBusy,
  values,
  maskedFlags,
  isLoading,
  connected,
  enabled,
  lastError,
  zigbee2mqttEnabled,
  frigateEnabled,
  saveDisabled,
  onRefresh,
  onSave,
  onChange,
}: Props) {
  const draftEnabled = Boolean(values?.enabled)

  return (
    <div className="space-y-3 sm:space-y-4">
      <IntegrationOverviewCard
        title={
          <div className="flex items-center gap-2">
            <Wifi className="h-4 w-4" />
            <span>MQTT</span>
          </div>
        }
        description="Configure the MQTT broker connection and operational settings."
        isAdmin={isAdmin}
        isBusy={isBusy}
        status={{ connected, enabled, lastError }}
        enableLabel="Enable MQTT"
        enabled={draftEnabled}
        onEnabledChange={(checked) => onChange('enabled', checked)}
        onRefresh={onRefresh}
        onSave={onSave}
        saveDisabled={saveDisabled}
      >
        {!isLoading && values && !draftEnabled ? (
          <Alert variant="warning">
            <AlertDescription>
              MQTT is disabled. Zigbee2MQTT and Frigate require MQTT.
              {zigbee2mqttEnabled || frigateEnabled ? (
                <>
                  {' '}
                  Currently enabled: {[zigbee2mqttEnabled ? 'Zigbee2MQTT' : null, frigateEnabled ? 'Frigate' : null].filter(Boolean).join(', ')}.
                </>
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard description="Configure MQTT broker connection settings.">
        <MqttSettingsForm
          values={values}
          maskedFlags={maskedFlags}
          isLoading={isLoading}
          isAdmin={isAdmin}
          onChange={onChange}
        />
      </IntegrationConnectionCard>
    </div>
  )
}
