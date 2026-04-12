/**
 * Card component for displaying and managing notification providers (ADR 0079).
 * Supports full CRUD: Create, Edit, Delete, Test.
 */
import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Badge } from '@/components/ui/badge'
import { Send, Home, Plus, Pencil, Trash2 } from 'lucide-react'
import { useHomeAssistantStatus } from '@/hooks/useHomeAssistant'
import {
  useNotificationProviders,
  useTestNotificationProvider,
  useDeleteNotificationProvider,
} from '../hooks/useNotificationProviders'
import { AddEditProviderModal } from './AddEditProviderModal'
import type { NotificationProvider } from '@/types/notifications'
import { getErrorMessage } from '@/types/errors'
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

export function NotificationProvidersCard({ isAdmin = false }: { isAdmin?: boolean }) {
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<NotificationProvider | null>(null)

  const providersQuery = useNotificationProviders()
  const testMutation = useTestNotificationProvider()
  const deleteMutation = useDeleteNotificationProvider()
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

  const allProviders = haSystemProvider ? [haSystemProvider, ...providers] : providers

  const handleTest = async (provider: NotificationProvider) => {
    setTestingId(provider.id)
    setTestResult(null)
    try {
      const result = await testMutation.mutateAsync(provider.id)
      setTestResult({ success: result.success, message: result.message })
    } catch (e) {
      setTestResult({ success: false, message: getErrorMessage(e) })
    } finally {
      setTestingId(null)
    }
  }

  const handleDelete = async (provider: NotificationProvider) => {
    if (!confirm(`Delete "${provider.name}"?`)) return
    try {
      await deleteMutation.mutateAsync(provider.id)
    } catch (e) {
      setTestResult({ success: false, message: `Delete failed: ${getErrorMessage(e)}` })
    }
  }

  const handleEdit = (provider: NotificationProvider) => {
    setEditingProvider(provider)
    setModalOpen(true)
  }

  const handleAdd = () => {
    setEditingProvider(null)
    setModalOpen(true)
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
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Notification Providers</CardTitle>
              <CardDescription>
                Configure notification providers for alarm alerts and rule actions.
              </CardDescription>
            </div>
            {isAdmin && (
              <Button size="sm" onClick={handleAdd}>
                <Plus className="mr-1 h-4 w-4" />
                Add
              </Button>
            )}
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
              {isAdmin
                ? 'No notification providers configured. Click "Add" to create one.'
                : 'No notification providers configured. Ask an administrator to add one.'}
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

                    <div className="flex items-center gap-1">
                      {!isSystemProvider && isAdmin && (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEdit(provider)}
                            title="Edit"
                            aria-label={`Edit ${provider.name}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void handleDelete(provider)}
                            disabled={deleteMutation.isPending}
                            title="Delete"
                            aria-label={`Delete ${provider.name}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void handleTest(provider)}
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

      <AddEditProviderModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        provider={editingProvider}
      />
    </>
  )
}
