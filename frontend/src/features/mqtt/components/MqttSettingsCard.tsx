import { Wifi } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
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
  onReset: () => void
  onSave: () => void
  onTest: () => void
  onClearPassword: () => void
  onSetDraft: (updater: (prev: MqttDraft | null) => MqttDraft | null) => void
  hasInitialDraft: boolean
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
  onReset,
  onSave,
  onTest,
  onClearPassword,
  onSetDraft,
  hasInitialDraft,
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
        description="Configure MQTT broker connection used by integrations (Home Assistant, Zigbee2MQTT, etc)."
        isAdmin={isAdmin}
        isBusy={isBusy}
        status={{ connected, enabled, lastError }}
        enableLabel="Enable MQTT"
        enableHelp="Enables the MQTT transport used by integrations like Zigbee2MQTT and the Home Assistant MQTT alarm entity."
        enabled={draft?.enabled ?? false}
        onEnabledChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, enabled: checked } : prev))}
        enableDisabled={!draft}
        onRefresh={onRefresh}
        onReset={onReset}
        onSave={onSave}
        resetDisabled={!hasInitialDraft}
        saveDisabled={!draft}
        opsActions={
          <Button type="button" variant="secondary" onClick={onTest} disabled={!isAdmin || isBusy || !draft}>
            Test Connection
          </Button>
        }
      >
        {!isLoading && draft && !draft.enabled ? (
          <Alert variant="warning">
            <AlertDescription>
              {settings?.enabled
                ? 'Saving with MQTT disabled will also disable Zigbee2MQTT and Frigate (they require MQTT).'
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

      <IntegrationConnectionCard description="Connection settings are read by the backend container.">
        <div className="space-y-3 sm:space-y-4">
          <MqttSettingsForm
            isAdmin={isAdmin}
            isBusy={isBusy}
            draft={draft}
            isLoading={isLoading}
            onClearPassword={onClearPassword}
            onSetDraft={onSetDraft}
          />
        </div>
      </IntegrationConnectionCard>
    </div>
  )
}
