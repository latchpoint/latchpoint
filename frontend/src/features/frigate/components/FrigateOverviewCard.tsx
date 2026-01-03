import { Camera } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import { BooleanStatusPill } from '@/features/integrations/components/BooleanStatusPill'
import { getErrorMessage } from '@/types/errors'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  mqttReady: boolean
  hasDraft: boolean
  draftEnabled: boolean
  onSetEnabled: (enabled: boolean) => void
  onSetError: (msg: string | null) => void
  onRefresh: () => void
  onReset: () => void
  onSave: () => void
  mqttConnected: boolean
  available: boolean | undefined
  ingestLastError: string | null | undefined
  ingestLastIngestAt: string | null | undefined
  rulesLastRunAt: string | null | undefined
  isLoading: boolean
  error: unknown
}

export function FrigateOverviewCard({
  isAdmin,
  isBusy,
  mqttReady,
  hasDraft,
  draftEnabled,
  onSetEnabled,
  onSetError,
  onRefresh,
  onReset,
  onSave,
  mqttConnected,
  available,
  ingestLastError,
  ingestLastIngestAt,
  rulesLastRunAt,
  isLoading,
  error,
}: Props) {
  const statusPills = (
    <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
      <BooleanStatusPill
        value={mqttConnected}
        trueLabel="MQTT: Connected"
        falseLabel="MQTT: Disconnected"
        trueVariant="default"
        falseVariant="muted"
        trueClassName="text-success"
      />
      <BooleanStatusPill
        value={!Boolean(ingestLastError)}
        trueLabel="Ingest OK"
        falseLabel="Ingest error"
        trueVariant="muted"
        falseVariant="default"
        falseClassName="text-destructive"
      />
    </div>
  )

  return (
    <IntegrationOverviewCard
      title={
        <div className="flex items-center gap-2">
          <Camera className="h-5 w-5" />
          <span>Frigate</span>
        </div>
      }
      description="Ingest Frigate MQTT person events so you can use them as conditions in alarm rules."
      isAdmin={isAdmin}
      isBusy={isBusy}
      status={{
        connected: Boolean(available),
        enabled: draftEnabled,
        lastError: ingestLastError,
        labels: { connected: 'Available', disconnected: 'Not available', disabled: 'Disabled' },
      }}
      statusExtra={statusPills}
      enableLabel="Enable Frigate ingest"
      enableHelp="Requires MQTT to be enabled first (Settings → MQTT)."
      enabled={draftEnabled}
      onEnabledChange={(checked) => {
        if (checked && !mqttReady) {
          onSetError('Enable MQTT first (Settings → MQTT) before enabling Frigate.')
          return
        }
        onSetEnabled(checked)
      }}
      enableDisabled={!hasDraft || (!draftEnabled && !mqttReady)}
      onRefresh={onRefresh}
      onReset={onReset}
      onSave={onSave}
      saveDisabled={!hasDraft}
    >
      <div className="space-y-3 sm:space-y-4">
        {!mqttReady ? (
          <Alert variant="warning">
            <AlertDescription>
              {draftEnabled
                ? 'Frigate is enabled, but MQTT is disabled. Frigate events will not be ingested until MQTT is enabled in Settings → MQTT.'
                : 'MQTT is not enabled/configured. Enable MQTT in Settings → MQTT before enabling Frigate.'}
            </AlertDescription>
          </Alert>
        ) : null}

        {isLoading ? (
          <LoadingInline label="Loading Frigate status…" />
        ) : error ? (
          <Alert variant="error">
            <AlertDescription>{getErrorMessage(error) || 'Failed to load Frigate status.'}</AlertDescription>
          </Alert>
        ) : (
          <div className="text-sm text-muted-foreground">
            Last ingest: {ingestLastIngestAt || '—'}
            {ingestLastError ? ` • Last error: ${ingestLastError}` : null}
            {rulesLastRunAt ? ` • Last rules run: ${rulesLastRunAt}` : null}
          </div>
        )}
      </div>
    </IntegrationOverviewCard>
  )
}
