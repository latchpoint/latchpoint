import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import { IntegrationConnectionCard } from '@/features/integrations/components/IntegrationConnectionCard'
import { getErrorMessage } from '@/types/errors'
import type { HaConnectionDraft } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'

type Props = {
  isAdmin: boolean
  draft: HaConnectionDraft | null
  isLoading: boolean
  isError: boolean
  loadError: unknown
}

export function HomeAssistantConnectionCard({
  isAdmin,
  draft,
  isLoading,
  isError,
  loadError,
}: Props) {
  return (
    <IntegrationConnectionCard
      title="Connection / setup"
      description="Home Assistant connection is configured via environment variables."
    >
      <div className="space-y-3">
        {draft ? (
          <>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <span className="text-muted-foreground">Enabled</span>
              <span>{draft.enabled ? 'Yes' : 'No'}</span>

              <span className="text-muted-foreground">Base URL</span>
              <span className="break-all">{draft.baseUrl || '(not set)'}</span>

              <span className="text-muted-foreground">Token</span>
              <span>{draft.hasToken ? 'Configured' : 'Not set'}</span>

              <span className="text-muted-foreground">Connect timeout</span>
              <span>{draft.connectTimeoutSeconds}s</span>
            </div>
          </>
        ) : !isAdmin ? (
          <div className="text-sm text-muted-foreground">Only admins can view Home Assistant settings.</div>
        ) : isError ? (
          <Alert variant="error">
            <AlertDescription>{getErrorMessage(loadError) || 'Failed to load Home Assistant settings.'}</AlertDescription>
          </Alert>
        ) : isLoading ? (
          <LoadingInline />
        ) : (
          <div className="text-sm text-muted-foreground">Home Assistant settings unavailable.</div>
        )}
      </div>
    </IntegrationConnectionCard>
  )
}
