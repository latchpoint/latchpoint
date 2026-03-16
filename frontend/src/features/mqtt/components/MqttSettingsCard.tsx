import { Wifi } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import type { MqttDraft } from '@/features/mqtt/hooks/useMqttSettingsModel'
import type { MqttSettings } from '@/types'
import { MqttSettingsForm } from '@/features/mqtt/components/MqttSettingsForm'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  draft: MqttDraft | null
  settings: MqttSettings | undefined
  isLoading: boolean
  connected: boolean | undefined
  enabled: boolean | undefined
  lastError: string | undefined
  zigbee2mqttEnabled: boolean
  frigateEnabled: boolean
  onRefresh: () => void
  onSetDraft: (updater: (prev: MqttDraft | null) => MqttDraft | null) => void
}

export function MqttSettingsCard({
  isAdmin,
  isBusy,
  draft,
  settings,
  isLoading,
  connected,
  enabled,
  lastError,
  zigbee2mqttEnabled,
  frigateEnabled,
  onRefresh,
  onSetDraft,
}: Props) {
  return (
    <div className="space-y-3 sm:space-y-4">
      <IntegrationOverviewCard
        title={
          <div className="flex items-center gap-2">
            <Wifi className="h-4 w-4" />
            <span>MQTT</span>
          </div>
        }
        description="MQTT broker connection is configured via environment variables."
        isAdmin={isAdmin}
        isBusy={isBusy}
        status={{ connected, enabled, lastError }}
        enableLabel="Enable MQTT"
        enableHelp="MQTT is enabled/disabled via environment variables."
        enabled={draft?.enabled ?? false}
        onEnabledChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, enabled: checked } : prev))}
        enableDisabled={true}
        onRefresh={onRefresh}
        onReset={() => {}}
        onSave={() => {}}
        resetDisabled={true}
        saveDisabled={true}
      >
        {!isLoading && draft && !draft.enabled ? (
          <Alert variant="warning">
            <AlertDescription>
              {settings?.enabled
                ? 'MQTT is being disabled. Zigbee2MQTT and Frigate require MQTT.'
                : 'MQTT is disabled. Zigbee2MQTT and Frigate cannot be enabled without MQTT.'}
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

      <IntegrationConnectionCard description="Connection settings are configured via environment variables.">
        <div className="space-y-3 sm:space-y-4">
          <MqttSettingsForm
            draft={draft}
            isLoading={isLoading}
          />
        </div>
      </IntegrationConnectionCard>
    </div>
  )
}
