import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import type { FrigateSettings } from '@/types'

type Props = {
  isAdmin: boolean
  settings: FrigateSettings | null
  isLoading: boolean
}

export function FrigateSettingsCard({ isAdmin, settings, isLoading }: Props) {
  return (
    <IntegrationConnectionCard title="Setup / settings" description="Frigate settings are configured via environment variables.">
      {!isAdmin ? (
        <div className="text-sm text-muted-foreground">Only admins can view Frigate settings.</div>
      ) : isLoading || !settings ? (
        <LoadingInline label="Loading Frigate settings…" />
      ) : (
        <div className="grid grid-cols-2 gap-2 text-sm">
          <span className="text-muted-foreground">Enabled</span>
          <span>{settings.enabled ? 'Yes' : 'No'}</span>

          <span className="text-muted-foreground">Events topic</span>
          <span className="break-all">{settings.eventsTopic || '(not set)'}</span>

          <span className="text-muted-foreground">Retention</span>
          <span>{settings.retentionSeconds}s</span>
        </div>
      )}
    </IntegrationConnectionCard>
  )
}
