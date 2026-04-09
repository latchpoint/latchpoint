import { Radio } from 'lucide-react'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Zigbee2mqttStatusPills } from '@/features/zigbee2mqtt/components/Zigbee2mqttStatusPills'
import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import type { Zigbee2mqttSettings } from '@/types'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  mqttReady: boolean
  mqttConnected: boolean
  z2mEnabled: boolean
  z2mConnected: boolean
  lastSyncAt: string | null
  lastDeviceCount: number | null
  lastSyncError: string | null
  settings: Zigbee2mqttSettings | null
  isLoadingSettings: boolean
  onRefresh: () => void
  onRunSync: () => void
}

export function Zigbee2mqttSettingsCard({
  isAdmin,
  isBusy,
  mqttReady,
  mqttConnected,
  z2mEnabled,
  z2mConnected,
  lastSyncAt,
  lastDeviceCount,
  lastSyncError,
  settings,
  isLoadingSettings,
  onRefresh,
  onRunSync,
}: Props) {
  const showAdminGate = !isAdmin
  const canSync = Boolean(z2mEnabled && mqttConnected)

  return (
    <div className="space-y-3 sm:space-y-4">
      <IntegrationOverviewCard
        title={
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4" />
            <span>Zigbee2MQTT</span>
          </div>
        }
        description="Zigbee2MQTT settings are configured via environment variables."
        isAdmin={isAdmin}
        isBusy={isBusy}
        statusExtra={
          <Zigbee2mqttStatusPills
            mqttConnected={mqttConnected}
            z2mEnabled={z2mEnabled}
            z2mConnected={z2mConnected}
            lastSyncAt={lastSyncAt}
            lastDeviceCount={lastDeviceCount}
            lastSyncError={lastSyncError}
          />
        }
        enableLabel={
          <span className="flex items-center gap-1">
            Enable Zigbee2MQTT
            <HelpTip content="Zigbee2MQTT is enabled/disabled via environment variables." />
          </span>
        }
        enabled={settings?.enabled ?? false}
        onEnabledChange={() => {}}
        enableDisabled={true}
        onRefresh={onRefresh}
        onReset={() => {}}
        onSave={() => {}}
        resetDisabled={true}
        saveDisabled={true}
        opsActions={
          <Button type="button" variant="secondary" onClick={onRunSync} disabled={!isAdmin || isBusy || !canSync}>
            Sync devices
          </Button>
        }
      >
        {showAdminGate ? (
          <div className="text-sm text-muted-foreground">Only admins can view Zigbee2MQTT settings.</div>
        ) : isLoadingSettings || !settings ? (
          <LoadingInline label="Loading Zigbee2MQTT settings…" />
        ) : !mqttReady ? (
          <Alert variant="warning">
            <AlertDescription>
              {settings.enabled
                ? 'Zigbee2MQTT is enabled, but MQTT is disabled. Zigbee2MQTT events will not be ingested until MQTT is enabled in Settings → MQTT.'
                : 'MQTT is not enabled/configured. Enable MQTT in Settings → MQTT before enabling Zigbee2MQTT.'}
            </AlertDescription>
          </Alert>
        ) : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard description="Settings are configured via environment variables.">
        {showAdminGate ? (
          <div className="text-sm text-muted-foreground">Only admins can view Zigbee2MQTT settings.</div>
        ) : isLoadingSettings || !settings ? (
          <LoadingInline label="Loading Zigbee2MQTT settings…" />
        ) : (
          <div className="grid grid-cols-2 gap-2 text-sm">
            <span className="text-muted-foreground">Enabled</span>
            <span>{settings.enabled ? 'Yes' : 'No'}</span>

            <span className="text-muted-foreground">Base topic</span>
            <span className="break-all">{settings.baseTopic || '(not set)'}</span>

            <span className="text-muted-foreground">Allowlist</span>
            <span>{settings.allowlist?.length ? (settings.allowlist as string[]).join(', ') : '(all devices)'}</span>

            <span className="text-muted-foreground">Denylist</span>
            <span>{settings.denylist?.length ? (settings.denylist as string[]).join(', ') : '(none)'}</span>

            <span className="text-muted-foreground">Run rules on event</span>
            <span>{settings.runRulesOnEvent ? 'Yes' : 'No'}</span>

            <span className="text-muted-foreground">Rules debounce</span>
            <span>{settings.runRulesDebounceSeconds ?? 5}s</span>

            <span className="text-muted-foreground">Rules max/min</span>
            <span>{settings.runRulesMaxPerMinute ?? 60}</span>

            <span className="text-muted-foreground">Rule kinds</span>
            <span>{settings.runRulesKinds?.length ? settings.runRulesKinds.join(', ') : '(none)'}</span>
          </div>
        )}
      </IntegrationConnectionCard>
    </div>
  )
}
