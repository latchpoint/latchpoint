/**
 * Card component for displaying notification providers (read-only)
 * Providers are now configured via environment variables (ADR-0075)
 */
import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Badge } from '@/components/ui/badge'
import { Send, Home } from 'lucide-react'
import { useHomeAssistantStatus } from '@/hooks/useHomeAssistant'
import {
  useNotificationProviders,
  useTestNotificationProvider,
} from '../hooks/useNotificationProviders'
import type { NotificationProvider } from '@/types/notifications'
import { HA_SYSTEM_PROVIDER_ID } from '@/lib/constants'

const PROVIDER_TYPE_LABELS: Record<string, string> = {
  pushbullet: 'Pushbullet',
  discord: 'Discord',
  slack: 'Slack',
  telegram: 'Telegram',
  pushover: 'Pushover',
  ntfy: 'Ntfy',
  email: 'Email (SMTP)',
  twilio_sms: 'Twilio SMS',
  twilio_call: 'Twilio Voice Call',
  webhook: 'Webhook',
  home_assistant: 'Home Assistant',
}

interface NotificationProvidersCardProps {
  isAdmin: boolean
}

export function NotificationProvidersCard({ isAdmin: _isAdmin }: NotificationProvidersCardProps) {
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const providersQuery = useNotificationProviders()
  const testMutation = useTestNotificationProvider()
  const haStatus = useHomeAssistantStatus()

  const isHaConfigured = haStatus.data?.configured ?? false
  const providers = providersQuery.data ?? []

  // Create virtual HA system provider when HA is configured
  const haSystemProvider: NotificationProvider | null = isHaConfigured
    ? {
        id: HA_SYSTEM_PROVIDER_ID,
        name: 'Home Assistant',
        providerType: 'home_assistant',
        config: {},
        isEnabled: true,
        createdAt: '',
        updatedAt: '',
      }
    : null

  // Combine HA system provider with user-configured providers
  const allProviders = haSystemProvider ? [haSystemProvider, ...providers] : providers

  const handleTest = async (provider: NotificationProvider) => {
    setTestingId(provider.id)
    setTestResult(null)
    try {
      const result = await testMutation.mutateAsync(provider.id)
      setTestResult({ success: result.success, message: result.message })
    } catch (e) {
      setTestResult({ success: false, message: String(e) })
    } finally {
      setTestingId(null)
    }
  }

  if (providersQuery.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Notification Providers</CardTitle>
        </CardHeader>
        <CardContent>
          <LoadingInline />
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Notification Providers</CardTitle>
          <CardDescription>
            Notification providers are configured via environment variables.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {testResult && (
          <Alert variant={testResult.success ? 'success' : 'error'}>
            <AlertDescription>{testResult.message}</AlertDescription>
          </Alert>
        )}

        {allProviders.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            No notification providers configured. Set provider environment variables to add providers.
          </div>
        ) : (
          <div className="space-y-2">
            {allProviders.map((provider) => {
              const isSystemProvider = provider.id === HA_SYSTEM_PROVIDER_ID

              return (
                <div
                  key={provider.id}
                  className="flex items-center justify-between rounded-md border p-3"
                >
                  <div className="flex items-center gap-3">
                    {isSystemProvider ? (
                      <div className="flex h-5 w-9 items-center justify-center">
                        <Home className="h-4 w-4 text-muted-foreground" />
                      </div>
                    ) : (
                      <Badge variant={provider.isEnabled ? 'default' : 'secondary'} className="text-xs">
                        {provider.isEnabled ? 'Enabled' : 'Disabled'}
                      </Badge>
                    )}
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{provider.name}</span>
                        <Badge variant="secondary">
                          {PROVIDER_TYPE_LABELS[provider.providerType] || provider.providerType}
                        </Badge>
                        {isSystemProvider && (
                          <Badge variant="outline" className="text-xs">
                            System
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleTest(provider)}
                      disabled={!provider.isEnabled || testingId === provider.id}
                    >
                      {testingId === provider.id ? (
                        <LoadingInline className="mr-2" />
                      ) : (
                        <Send className="mr-2 h-4 w-4" />
                      )}
                      Test
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
