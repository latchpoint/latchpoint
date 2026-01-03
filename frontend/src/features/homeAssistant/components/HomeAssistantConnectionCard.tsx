import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
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
  isPending: boolean
  onClearToken: () => void
  onSetDraft: (updater: (prev: HaConnectionDraft | null) => HaConnectionDraft | null) => void
}

export function HomeAssistantConnectionCard({
  isAdmin,
  draft,
  isLoading,
  isError,
  loadError,
  isPending,
  onClearToken,
  onSetDraft,
}: Props) {
  return (
    <IntegrationConnectionCard
      title="Connection / setup"
      description="Configure the Home Assistant URL and token used for entity import, notify services, and other integrations."
    >
      <div className="space-y-3">
        {draft ? (
          <>
            <FormField
              label="Base URL"
              htmlFor="haBaseUrl"
              help="Home Assistant instance URL (e.g., http://homeassistant.local:8123). Must be reachable from the backend container."
              required={draft.enabled}
            >
              <Input
                id="haBaseUrl"
                placeholder="http://localhost:8123"
                value={draft.baseUrl}
                onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, baseUrl: e.target.value } : prev))}
                disabled={!isAdmin || isPending || !draft.enabled}
              />
            </FormField>

            <FormField
              label="Token"
              htmlFor="haToken"
              help={
                draft.hasToken && !draft.tokenTouched
                  ? 'A token is already saved. Leave blank to keep it, or enter a new token to replace it.'
                  : 'Use a Home Assistant long-lived access token.'
              }
              required={draft.enabled && !draft.hasToken}
            >
              <Input
                id="haToken"
                type="password"
                value={draft.token}
                onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, token: e.target.value, tokenTouched: true } : prev))}
                disabled={!isAdmin || isPending || !draft.enabled}
              />
              {draft.hasToken ? (
                <div className="mt-2">
                  <Button type="button" size="sm" variant="destructive" onClick={onClearToken} disabled={!isAdmin || isPending}>
                    Clear token
                  </Button>
                </div>
              ) : null}
            </FormField>

            <FormField label="Connect timeout (seconds)" htmlFor="haConnectTimeout" help="HTTP connection timeout used when talking to Home Assistant.">
              <Input
                id="haConnectTimeout"
                inputMode="decimal"
                value={draft.connectTimeoutSeconds}
                onChange={(e) => onSetDraft((prev) => (prev ? { ...prev, connectTimeoutSeconds: e.target.value } : prev))}
                disabled={!isAdmin || isPending}
              />
            </FormField>
          </>
        ) : !isAdmin ? (
          <div className="text-sm text-muted-foreground">Only admins can view and edit Home Assistant settings.</div>
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
