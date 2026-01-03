import { Home } from 'lucide-react'
import { BooleanStatusPill } from '@/features/integrations/components/BooleanStatusPill'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'
import type { HaConnectionDraft } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  draft: HaConnectionDraft | null
  reachable: boolean | undefined
  configured: boolean | undefined
  lastError: string | null | undefined
  onRefresh: () => void
  onReset: () => void
  onSave: () => void
  onSetDraft: (updater: (prev: HaConnectionDraft | null) => HaConnectionDraft | null) => void
}

export function HomeAssistantOverviewCard({
  isAdmin,
  isBusy,
  draft,
  reachable,
  configured,
  lastError,
  onRefresh,
  onReset,
  onSave,
  onSetDraft,
}: Props) {
  return (
    <IntegrationOverviewCard
      title={
        <div className="flex items-center gap-2">
          <Home className="h-4 w-4" />
          <span>Home Assistant</span>
        </div>
      }
      description="Connect to Home Assistant for entity import, notify services, and related integrations."
      isAdmin={isAdmin}
      isBusy={isBusy}
      status={{
        connected: reachable,
        enabled: draft?.enabled,
        lastError,
        labels: { connected: 'Reachable', disconnected: 'Not reachable', disabled: 'Disabled' },
      }}
      statusExtra={
        <div className="flex flex-wrap gap-1.5 sm:gap-2">
          <BooleanStatusPill
            value={Boolean(configured)}
            trueLabel="Configured"
            falseLabel="Not configured"
            trueVariant="default"
            falseVariant="default"
            trueClassName="text-success"
            falseClassName="text-muted-foreground"
          />
        </div>
      }
      enableLabel="Enable Home Assistant"
      enableHelp="Enables Home Assistant integration features (entity import, notify services, MQTT alarm entity management)."
      enabled={draft?.enabled ?? false}
      onEnabledChange={(checked) => onSetDraft((prev) => (prev ? { ...prev, enabled: checked } : prev))}
      enableDisabled={!draft}
      onRefresh={onRefresh}
      onReset={onReset}
      onSave={onSave}
      saveDisabled={!draft}
    />
  )
}

