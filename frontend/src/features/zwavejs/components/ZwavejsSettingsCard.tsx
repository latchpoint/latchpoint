import { Radio } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import type { ZwavejsDraft } from '@/features/zwavejs/hooks/useZwavejsSettingsModel'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  draft: ZwavejsDraft | null
  isLoading: boolean
  connected: boolean | undefined
  enabled: boolean | undefined
  lastError: string | null | undefined
  hasInitialDraft: boolean
  onRefresh: () => void
  onReset: () => void
  onSave: () => void
  onTest: () => void
  onSync: () => void
  onSetDraft: (updater: (prev: ZwavejsDraft | null) => ZwavejsDraft | null) => void
}

export function ZwavejsSettingsCard({
  isAdmin,
  isBusy,
  draft,
  isLoading,
  connected,
  enabled,
  lastError,
  hasInitialDraft,
  onRefresh,
  onReset,
  onSave,
  onTest,
  onSync,
  onSetDraft,
}: Props) {
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
        enableHelp="Enables the Z-Wave JS integration used for entity sync and set-value operations."
        enabled={draft?.enabled ?? false}
        onEnabledChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, enabled: checked } : prev))}
        enableDisabled={!draft}
        onRefresh={onRefresh}
        onReset={onReset}
        onSave={onSave}
        resetDisabled={!hasInitialDraft}
        saveDisabled={!draft}
        opsActions={
          <>
            <Button type="button" variant="secondary" onClick={onTest} disabled={!isAdmin || isBusy || !draft}>
              Test Connection
            </Button>
            <Button type="button" variant="outline" onClick={onSync} disabled={!isAdmin || isBusy || !draft}>
              Sync Entities
            </Button>
          </>
        }
      >
        {isLoading && !draft ? <LoadingInline /> : !draft ? <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div> : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard description="Connection settings are read by the backend container.">
        {isLoading && !draft ? (
          <LoadingInline />
        ) : !draft ? (
          <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div>
        ) : (
          <div className="space-y-3 sm:space-y-4">
            <FormField
              label="WebSocket URL"
              htmlFor="zwaveWsUrl"
              help="WebSocket endpoint for Z-Wave JS UI / zwave-js-server (reachable from the backend container)."
              required={draft.enabled}
            >
              <Input
                id="zwaveWsUrl"
                placeholder="ws://localhost:3000"
                value={draft.wsUrl}
                onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, wsUrl: e.target.value } : prev))}
                disabled={!isAdmin || isBusy}
              />
              <div className="mt-1 text-xs text-muted-foreground">Z-Wave JS UI / zwave-js-server commonly uses WS port 3000.</div>
            </FormField>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
              <FormField label="Connect timeout (s)" htmlFor="zwaveConnectTimeout" help="How long to wait when establishing the WebSocket connection." required>
                <Input
                  id="zwaveConnectTimeout"
                  inputMode="decimal"
                  value={draft.connectTimeoutSeconds}
                  onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, connectTimeoutSeconds: e.target.value } : prev))}
                  disabled={!isAdmin || isBusy}
                />
              </FormField>

              <FormField label="Reconnect min (s)" htmlFor="zwaveReconnectMin" help="Minimum delay before attempting to reconnect after a disconnect." required>
                <Input
                  id="zwaveReconnectMin"
                  inputMode="numeric"
                  value={draft.reconnectMinSeconds}
                  onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, reconnectMinSeconds: e.target.value } : prev))}
                  disabled={!isAdmin || isBusy}
                />
              </FormField>

              <FormField label="Reconnect max (s)" htmlFor="zwaveReconnectMax" help="Maximum delay between reconnect attempts (must be ≥ reconnect min)." required>
                <Input
                  id="zwaveReconnectMax"
                  inputMode="numeric"
                  value={draft.reconnectMaxSeconds}
                  onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, reconnectMaxSeconds: e.target.value } : prev))}
                  disabled={!isAdmin || isBusy}
                />
              </FormField>
            </div>
          </div>
        )}
      </IntegrationConnectionCard>
    </div>
  )
}
