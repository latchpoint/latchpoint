/**
 * Modal for creating or editing a notification provider (ADR 0079 Phase 4).
 * Renders a schema-driven form from the provider type's config_schema.
 */

import { useEffect, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Switch } from '@/components/ui/switch'
import { IntegrationSettingsForm } from '@/features/integrations/components/IntegrationSettingsForm'
import {
  useCreateNotificationProvider,
  useNotificationProviderTypes,
  useUpdateNotificationProvider,
} from '../hooks/useNotificationProviders'
import { getErrorMessage } from '@/types/errors'
import type { NotificationProvider } from '@/types/notifications'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** If provided, we're editing. Otherwise creating. */
  provider?: NotificationProvider | null
}

export function AddEditProviderModal({ open, onOpenChange, provider }: Props) {
  const isEdit = Boolean(provider)
  const providerTypesQuery = useNotificationProviderTypes()
  const createMutation = useCreateNotificationProvider()
  const updateMutation = useUpdateNotificationProvider()

  const [name, setName] = useState('')
  const [providerType, setProviderType] = useState('')
  const [isEnabled, setIsEnabled] = useState(true)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [error, setError] = useState<string | null>(null)

  // Initialize form when modal opens or provider changes
  useEffect(() => {
    if (!open) return
    queueMicrotask(() => {
      if (provider) {
        setName(provider.name)
        setProviderType(provider.providerType)
        setIsEnabled(provider.isEnabled)
        const values: Record<string, unknown> = {}
        for (const [key, value] of Object.entries(provider.config)) {
          if (!key.startsWith('has')) {
            values[key] = value
          }
        }
        setConfig(values)
      } else {
        setName('')
        setProviderType('')
        setIsEnabled(true)
        setConfig({})
      }
      setError(null)
    })
  }, [open, provider])

  const providerTypes = providerTypesQuery.data ?? []
  const selectedType = providerTypes.find((t) => t.type === providerType)

  // Extract masked flags from existing provider config
  const maskedFlags: Record<string, boolean> = {}
  if (provider) {
    for (const [key, value] of Object.entries(provider.config)) {
      if (key.startsWith('has') && typeof value === 'boolean') {
        maskedFlags[key] = value
      }
    }
  }

  const handleConfigChange = (key: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async () => {
    setError(null)
    if (!name.trim()) {
      setError('Name is required.')
      return
    }
    if (!providerType) {
      setError('Provider type is required.')
      return
    }

    try {
      if (isEdit && provider) {
        await updateMutation.mutateAsync({
          id: provider.id,
          data: { name: name.trim(), isEnabled, config },
        })
      } else {
        await createMutation.mutateAsync({
          name: name.trim(),
          providerType,
          config,
          isEnabled,
        })
      }
      onOpenChange(false)
    } catch (err) {
      setError(getErrorMessage(err) || `Failed to ${isEdit ? 'update' : 'create'} provider.`)
    }
  }

  const isBusy = createMutation.isPending || updateMutation.isPending

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={isEdit ? 'Edit Provider' : 'Add Provider'}
      maxWidthClassName="max-w-lg"
    >
      <div className="space-y-4">
        {error && (
          <Alert variant="error">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <FormField label="Name" htmlFor="provider-name" required size="compact">
          <Input
            id="provider-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Discord Alerts"
            disabled={isBusy}
          />
        </FormField>

        {!isEdit && (
          <FormField label="Provider Type" htmlFor="provider-type" required size="compact">
            <select
              id="provider-type"
              value={providerType}
              onChange={(e) => {
                setProviderType(e.target.value)
                setConfig({})
              }}
              disabled={isBusy}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="">Select a provider type...</option>
              {providerTypes.map((t) => (
                <option key={t.type} value={t.type}>
                  {t.displayName}
                </option>
              ))}
            </select>
          </FormField>
        )}

        <FormField label="Enabled" size="compact">
          <Switch checked={isEnabled} onCheckedChange={setIsEnabled} disabled={isBusy} />
        </FormField>

        {selectedType?.configSchema && (
          <div className="rounded-md border p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Configuration
            </div>
            <IntegrationSettingsForm
              schema={selectedType.configSchema as import('@/types/settingsRegistry').ConfigSchema}
              encryptedFields={selectedType.encryptedFields ?? []}
              values={config}
              maskedFlags={maskedFlags}
              disabled={isBusy}
              onChange={handleConfigChange}
            />
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isBusy}>
            Cancel
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={isBusy || !name.trim() || !providerType}>
            {isBusy ? 'Saving...' : isEdit ? 'Save' : 'Create'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
