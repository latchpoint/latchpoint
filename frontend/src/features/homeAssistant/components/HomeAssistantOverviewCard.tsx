import { Home } from 'lucide-react'
import { BooleanStatusPill } from '@/features/integrations/components/BooleanStatusPill'
import { IntegrationOverviewCard } from '@/features/integrations/components/IntegrationOverviewCard'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  enabled: boolean
  reachable: boolean | undefined
  configured: boolean | undefined
  lastError: string | null | undefined
  saveDisabled: boolean
  onRefresh: () => void
  onSave: () => void
  onEnabledChange: (checked: boolean) => void
}

export function HomeAssistantOverviewCard({
  isAdmin,
  isBusy,
  enabled,
  reachable,
  configured,
  lastError,
  saveDisabled,
  onRefresh,
  onSave,
  onEnabledChange,
}: Props) {
  return (
    <IntegrationOverviewCard
      title={
        <div className="flex items-center gap-2">
          <Home className="h-4 w-4" />
          <span>Home Assistant</span>
        </div>
      }
      description="Configure the Home Assistant integration connection and settings."
      isAdmin={isAdmin}
      isBusy={isBusy}
      status={{
        connected: reachable,
        enabled,
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
      enabled={enabled}
      onEnabledChange={onEnabledChange}
      onRefresh={onRefresh}
      onSave={onSave}
      saveDisabled={saveDisabled}
    />
  )
}
