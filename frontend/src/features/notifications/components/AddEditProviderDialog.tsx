/**
 * Dialog for adding or editing notification providers
 */
import { useState, useEffect } from 'react'
import { Modal } from '@/components/ui/modal'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import {
  useCreateNotificationProvider,
  useUpdateNotificationProvider,
} from '../hooks/useNotificationProviders'
import { PushbulletProviderForm } from './PushbulletProviderForm'
import type {
  NotificationProvider,
  NotificationProviderType,
  PushbulletConfig,
} from '@/types/notifications'

const PROVIDER_TYPES: {
  value: NotificationProviderType
  label: string
}[] = [
  { value: 'pushbullet', label: 'Pushbullet' },
  { value: 'discord', label: 'Discord' },
  { value: 'slack', label: 'Slack' },
  { value: 'webhook', label: 'Webhook' },
  // home_assistant is a system provider, shown automatically when HA is configured
]

interface AddEditProviderDialogProps {
  open: boolean
  onClose: () => void
  provider: NotificationProvider | null
}

export function AddEditProviderDialog({
  open,
  onClose,
  provider,
}: AddEditProviderDialogProps) {
  const isEditing = Boolean(provider)

  const [name, setName] = useState('')
  const [providerType, setProviderType] = useState<NotificationProviderType>('pushbullet')
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [error, setError] = useState<string | null>(null)

  const createMutation = useCreateNotificationProvider()
  const updateMutation = useUpdateNotificationProvider()

  const isBusy = createMutation.isPending || updateMutation.isPending

  // Reset form when dialog opens/closes or provider changes
  useEffect(() => {
    if (open) {
      if (provider) {
        setName(provider.name)
        setProviderType(provider.providerType)
        setConfig(provider.config)
      } else {
        setName('')
        setProviderType('pushbullet')
        setConfig({ accessToken: '' })
      }
      setError(null)
    }
  }, [open, provider])

  const toPushbulletConfig = (rawConfig: Record<string, unknown>): PushbulletConfig => {
    const accessToken = typeof rawConfig.accessToken === 'string' ? rawConfig.accessToken : ''
    const targetType =
      rawConfig.targetType === 'all' ||
      rawConfig.targetType === 'device' ||
      rawConfig.targetType === 'email' ||
      rawConfig.targetType === 'channel'
        ? rawConfig.targetType
        : undefined

    return {
      accessToken,
      targetType,
      defaultDeviceIden:
        typeof rawConfig.defaultDeviceIden === 'string' ? rawConfig.defaultDeviceIden : undefined,
      defaultEmail: typeof rawConfig.defaultEmail === 'string' ? rawConfig.defaultEmail : undefined,
      defaultChannelTag:
        typeof rawConfig.defaultChannelTag === 'string' ? rawConfig.defaultChannelTag : undefined,
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!name.trim()) {
      setError('Name is required')
      return
    }

    try {
      if (isEditing && provider) {
        await updateMutation.mutateAsync({
          id: provider.id,
          data: { name, config },
        })
      } else {
        await createMutation.mutateAsync({
          name,
          providerType,
          config,
        })
      }
      onClose()
    } catch (e: unknown) {
      // API errors are plain objects with a message property, not Error instances
      const message =
        e && typeof e === 'object' && 'message' in e
          ? String(e.message)
          : 'Failed to save provider'
      setError(message)
    }
  }

  const renderProviderForm = () => {
    switch (providerType) {
      case 'pushbullet':
        return (
          <PushbulletProviderForm
            config={toPushbulletConfig(config)}
            onChange={(pbConfig) => setConfig(pbConfig as unknown as Record<string, unknown>)}
            disabled={isBusy}
            existingProviderId={provider?.id}
          />
        )

      case 'discord':
        return (
          <FormField
            label="Webhook URL"
            htmlFor="discord-webhook"
            required
            help="Right-click channel > Edit > Integrations > Webhooks"
          >
            <Input
              id="discord-webhook"
              value={(config.webhookUrl as string) || ''}
              onChange={(e) => setConfig({ ...config, webhookUrl: e.target.value })}
              placeholder="https://discord.com/api/webhooks/..."
              disabled={isBusy}
            />
          </FormField>
        )

      case 'slack':
        return (
          <div className="space-y-4">
            <FormField
              label="Bot Token"
              htmlFor="slack-bot-token"
              required
              help="Slack Bot token (starts with xoxb-)"
            >
              <Input
                id="slack-bot-token"
                value={(config.botToken as string) || ''}
                onChange={(e) => setConfig({ ...config, botToken: e.target.value })}
                placeholder="xoxb-..."
                disabled={isBusy}
              />
            </FormField>
            <FormField
              label="Default Channel"
              htmlFor="slack-default-channel"
              required
              help="Channel ID (recommended), e.g. C0123456789"
            >
              <Input
                id="slack-default-channel"
                value={(config.defaultChannel as string) || ''}
                onChange={(e) => setConfig({ ...config, defaultChannel: e.target.value })}
                placeholder="C0123456789"
                disabled={isBusy}
              />
            </FormField>
            <FormField label="Default Username" htmlFor="slack-default-username">
              <Input
                id="slack-default-username"
                value={(config.defaultUsername as string) || ''}
                onChange={(e) => setConfig({ ...config, defaultUsername: e.target.value })}
                placeholder="Alarm System"
                disabled={isBusy}
              />
            </FormField>
            <FormField label="Default Icon Emoji" htmlFor="slack-default-icon-emoji">
              <Input
                id="slack-default-icon-emoji"
                value={(config.defaultIconEmoji as string) || ''}
                onChange={(e) => setConfig({ ...config, defaultIconEmoji: e.target.value })}
                placeholder=":rotating_light:"
                disabled={isBusy}
              />
            </FormField>
          </div>
        )

      case 'webhook':
        return (
          <div className="space-y-4">
            <FormField label="URL" htmlFor="webhook-url" required>
              <Input
                id="webhook-url"
                value={(config.url as string) || ''}
                onChange={(e) => setConfig({ ...config, url: e.target.value })}
                placeholder="https://..."
                disabled={isBusy}
              />
            </FormField>
            <FormField label="Method" htmlFor="webhook-method">
              <Select
                id="webhook-method"
                value={(config.method as string) || 'POST'}
                onChange={(e) => setConfig({ ...config, method: e.target.value })}
                disabled={isBusy}
              >
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
              </Select>
            </FormField>
          </div>
        )

      default:
        return (
          <Alert variant="info">
            <AlertDescription>
              Configuration for this provider type is not yet implemented.
            </AlertDescription>
          </Alert>
        )
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(open) => !open && onClose()}
      title={isEditing ? 'Edit Notification Provider' : 'Add Notification Provider'}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <Alert variant="error">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <FormField label="Display Name" htmlFor="provider-name" required>
          <Input
            id="provider-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Notification Provider"
            disabled={isBusy}
          />
        </FormField>

        {!isEditing && (
          <FormField label="Provider Type" htmlFor="provider-type" required>
            <Select
              id="provider-type"
              value={providerType}
              onChange={(e) => {
                const nextType = e.target.value as NotificationProviderType
                setProviderType(nextType)
                setConfig(nextType === 'pushbullet' ? { accessToken: '' } : {})
              }}
              disabled={isBusy}
            >
              {PROVIDER_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        <div className="border-t pt-4">
          {renderProviderForm()}
        </div>

        <div className="flex justify-end gap-2 border-t pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={isBusy}>
            Cancel
          </Button>
          <Button type="submit" disabled={isBusy}>
            {isBusy && <LoadingInline className="mr-2" />}
            {isEditing ? 'Save Changes' : 'Add Provider'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
