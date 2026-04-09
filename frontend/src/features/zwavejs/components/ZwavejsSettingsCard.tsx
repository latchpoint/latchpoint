import { Radio } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import type { ZwavejsSettings } from '@/types'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  settings: ZwavejsSettings | null
  isLoading: boolean
  connected: boolean | undefined
  enabled: boolean | undefined
  lastError: string | null | undefined
  onRefresh: () => void
  onSync: () => void
}

export function ZwavejsSettingsCard({
  isAdmin,
  isBusy,
  settings,
  isLoading,
  connected,
  enabled,
  lastError,
  onRefresh,
  onSync,
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
        description="Z-Wave JS settings are configured via environment variables."
        isAdmin={isAdmin}
        isBusy={isBusy}
        status={{ connected, enabled, lastError }}
        enableLabel="Enable Z-Wave JS"
        enableHelp="Z-Wave JS is enabled/disabled via environment variables."
        enabled={settings?.enabled ?? enabled ?? false}
        onEnabledChange={() => {}}
        enableDisabled={true}
        onRefresh={onRefresh}
        opsActions={
          <Button type="button" variant="outline" onClick={onSync} disabled={!isAdmin || isBusy || !settings}>
            Sync Entities
          </Button>
        }
      >
        {isLoading && !settings ? <LoadingInline /> : !settings ? <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div> : null}
      </IntegrationOverviewCard>

      <IntegrationConnectionCard description="Connection settings are configured via environment variables.">
        {isLoading && !settings ? (
          <LoadingInline />
        ) : !settings ? (
          <div className="text-sm text-muted-foreground">Z-Wave JS settings unavailable.</div>
        ) : (
          <div className="grid grid-cols-2 gap-2 text-sm">
            <span className="text-muted-foreground">Enabled</span>
            <span>{settings.enabled ? 'Yes' : 'No'}</span>

            <span className="text-muted-foreground">WebSocket URL</span>
            <span className="break-all">{settings.wsUrl || '(not set)'}</span>

            <span className="text-muted-foreground">API token</span>
            <span>{settings.hasApiToken ? 'Configured' : 'Not set'}</span>

            <span className="text-muted-foreground">Connect timeout</span>
            <span>{settings.connectTimeoutSeconds}s</span>

            <span className="text-muted-foreground">Reconnect min</span>
            <span>{settings.reconnectMinSeconds}s</span>

            <span className="text-muted-foreground">Reconnect max</span>
            <span>{settings.reconnectMaxSeconds}s</span>
          </div>
        )}
      </IntegrationConnectionCard>
    </div>
  )
}
