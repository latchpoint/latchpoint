import { Radio } from 'lucide-react'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Alert, AlertDescription } from '@/components/ui/alert'
import type { Zigbee2mqttDraft } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'
import { Zigbee2mqttStatusPills } from '@/features/zigbee2mqtt/components/Zigbee2mqttStatusPills'
import { Zigbee2mqttRulesAndPanelSection } from '@/features/zigbee2mqtt/components/Zigbee2mqttRulesAndPanelSection'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'

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
  draft: Zigbee2mqttDraft | null
  isLoadingDraft: boolean
  onUpdateDraft: (patch: Partial<Zigbee2mqttDraft>) => void
  onSetError: (msg: string | null) => void
  onRefresh: () => void
  onSave: () => void
  onReset: () => void
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
  draft,
  isLoadingDraft,
  onUpdateDraft,
  onSetError,
  onRefresh,
  onSave,
  onReset,
  onRunSync,
}: Props) {
  const showAdminGate = !isAdmin

  const canSync = Boolean(draft?.enabled && mqttConnected)

  return (
    <div className="space-y-3 sm:space-y-4">
      <IntegrationOverviewCard
        title={
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4" />
            <span>Zigbee2MQTT</span>
          </div>
        }
        description="Sync Zigbee devices from Zigbee2MQTT via MQTT and ingest state/action updates (Home Assistant not required)."
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
            <HelpTip content="Requires MQTT to be enabled first (Settings → MQTT)." />
          </span>
        }
        enabled={draft?.enabled ?? false}
        onEnabledChange={(checked) => {
          if (checked && !mqttReady) {
            onSetError('Enable MQTT first (Settings → MQTT) before enabling Zigbee2MQTT.')
            return
          }
          onUpdateDraft({ enabled: checked })
        }}
        enableDisabled={!draft || (!draft?.enabled && !mqttReady)}
        onRefresh={onRefresh}
        onReset={onReset}
        onSave={onSave}
        saveDisabled={!draft}
        opsActions={
          <Button type="button" variant="secondary" onClick={onRunSync} disabled={!isAdmin || isBusy || !canSync}>
            Sync devices
          </Button>
        }
      >
        {showAdminGate ? (
          <div className="text-sm text-muted-foreground">Only admins can view and edit Zigbee2MQTT settings.</div>
        ) : isLoadingDraft || !draft ? (
          <LoadingInline label="Loading Zigbee2MQTT settings…" />
        ) : !mqttReady ? (
          <Alert variant="warning">
            <AlertDescription>
              {draft.enabled
                ? 'Zigbee2MQTT is enabled, but MQTT is disabled. Zigbee2MQTT events will not be ingested until MQTT is enabled in Settings → MQTT.'
                : 'MQTT is not enabled/configured. Enable MQTT in Settings → MQTT before enabling Zigbee2MQTT.'}
            </AlertDescription>
          </Alert>
        ) : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard title="Setup / settings">
        {showAdminGate ? (
          <div className="text-sm text-muted-foreground">Only admins can view and edit Zigbee2MQTT settings.</div>
        ) : isLoadingDraft || !draft ? (
          <LoadingInline label="Loading Zigbee2MQTT settings…" />
        ) : (
          <div className="space-y-3 sm:space-y-4">
            <FormField label="Base topic" htmlFor="z2mBaseTopic" help="Zigbee2MQTT base topic (default: zigbee2mqtt).">
              <Input
                id="z2mBaseTopic"
                value={draft.baseTopic}
                onChange={(e) => onUpdateDraft({ baseTopic: e.target.value })}
                placeholder="zigbee2mqtt"
                disabled={!isAdmin || isBusy}
              />
            </FormField>

            <Zigbee2mqttRulesAndPanelSection isAdmin={isAdmin} isBusy={isBusy} draft={draft} onUpdateDraft={onUpdateDraft} />
          </div>
        )}
      </IntegrationConnectionCard>
    </div>
  )
}
