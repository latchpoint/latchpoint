import { Radio } from 'lucide-react'
import { Button } from '@/components/ui/button'
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
  onRefresh: () => void
  onSave: () => void
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
  onRefresh,
  onSave,
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
        enableHelp="Enable or disable the Z-Wave JS integration."
        enabled={draft?.enabled ?? false}
        onEnabledChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, enabled: checked } : prev))}
        enableDisabled={!draft}
        onRefresh={onRefresh}
        onSave={onSave}
        saveDisabled={!draft || draft.enabled === (enabled ?? false)}
        opsActions={
          <Button type="button" variant="outline" onClick={onSync} disabled={!isAdmin || isBusy || !draft}>
            Sync Entities
          </Button>
        }
      >
        {isLoading && !draft ? <LoadingInline /> : !draft ? <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div> : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard description="Connection settings are configured via environment variables.">
        {isLoading && !draft ? (
          <LoadingInline />
        ) : !draft ? (
          <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div>
        ) : (
          <div className="grid grid-cols-2 gap-2 text-sm">
            <span className="text-muted-foreground">WebSocket URL</span>
            <span className="break-all">{draft.wsUrl || '(not set)'}</span>

            <span className="text-muted-foreground">API Token</span>
            <span>{draft.hasApiToken ? 'Configured' : 'Not set'}</span>

            <span className="text-muted-foreground">Connect timeout</span>
            <span>{draft.connectTimeoutSeconds}s</span>

            <span className="text-muted-foreground">Reconnect min</span>
            <span>{draft.reconnectMinSeconds}s</span>

            <span className="text-muted-foreground">Reconnect max</span>
            <span>{draft.reconnectMaxSeconds}s</span>
          </div>
        )}
      </IntegrationConnectionCard>
    </div>
  )
}
