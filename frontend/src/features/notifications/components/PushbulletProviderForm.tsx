/**
 * Pushbullet notification provider configuration form
 * Allows users to configure Pushbullet access tokens and default targets
 */
import { useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Check, AlertCircle, RefreshCw } from 'lucide-react'
import { notificationsService } from '@/services/notifications'
import type { PushbulletConfig, PushbulletDevice, PushbulletTargetType } from '@/types/notifications'

interface PushbulletProviderFormProps {
  config: PushbulletConfig
  onChange: (config: PushbulletConfig) => void
  disabled?: boolean
  existingProviderId?: string
}

export function PushbulletProviderForm({
  config,
  onChange,
  disabled = false,
  existingProviderId,
}: PushbulletProviderFormProps) {
  const [devices, setDevices] = useState<PushbulletDevice[]>([])
  const [isLoadingDevices, setIsLoadingDevices] = useState(false)
  const [tokenValidation, setTokenValidation] = useState<{
    checked: boolean
    valid: boolean | null
    userName?: string
    error?: string
  }>({ checked: false, valid: null })

  const targetType = config.targetType || 'all'

  const handleTokenChange = (value: string) => {
    onChange({ ...config, accessToken: value })
    // Reset validation when token changes
    setTokenValidation({ checked: false, valid: null })
  }

  const handleTargetTypeChange = (newType: PushbulletTargetType) => {
    onChange({
      ...config,
      targetType: newType,
      // Clear other target fields when switching type
      defaultDeviceIden: newType === 'device' ? config.defaultDeviceIden : undefined,
      defaultEmail: newType === 'email' ? config.defaultEmail : undefined,
      defaultChannelTag: newType === 'channel' ? config.defaultChannelTag : undefined,
    })
  }

  const validateToken = useCallback(async () => {
    if (!config.accessToken) {
      setTokenValidation({ checked: true, valid: false, error: 'Access token is required' })
      return
    }

    try {
      const result = await notificationsService.validatePushbulletToken(config.accessToken)
      setTokenValidation({
        checked: true,
        valid: result.valid,
        userName: result.user?.name,
        error: result.error,
      })
    } catch {
      setTokenValidation({
        checked: true,
        valid: false,
        error: 'Failed to validate token',
      })
    }
  }, [config.accessToken])

  const fetchDevices = useCallback(async () => {
    if (!config.accessToken) return

    setIsLoadingDevices(true)
    try {
      let fetchedDevices: PushbulletDevice[]
      if (existingProviderId) {
        fetchedDevices = await notificationsService.getPushbulletDevicesByProvider(existingProviderId)
      } else {
        fetchedDevices = await notificationsService.getPushbulletDevices(config.accessToken)
      }
      setDevices(Array.isArray(fetchedDevices) ? fetchedDevices : [])
    } catch {
      setDevices([])
    } finally {
      setIsLoadingDevices(false)
    }
  }, [config.accessToken, existingProviderId])

  const showTokenValidationIcon = () => {
    if (!tokenValidation.checked) return null
    if (tokenValidation.valid === true) {
      return <Check className="h-4 w-4 text-success" />
    }
    if (tokenValidation.valid === false) {
      return <AlertCircle className="h-4 w-4 text-destructive" />
    }
    return null
  }

  return (
    <div className="space-y-4">
      {/* Access Token */}
      <FormField
        label="Access Token"
        htmlFor="pb-access-token"
        required
        help="Get from pushbullet.com -> Settings -> Access Tokens"
      >
        <div className="flex items-center gap-2">
          <Input
            id="pb-access-token"
            type="password"
            value={config.accessToken}
            onChange={(e) => handleTokenChange(e.target.value)}
            onBlur={validateToken}
            placeholder="o.xxxxxxxxxxxxxxxxxxxxxxxxx"
            disabled={disabled}
            className="flex-1"
          />
          {showTokenValidationIcon()}
        </div>
        {tokenValidation.checked && tokenValidation.valid && tokenValidation.userName && (
          <p className="mt-1 text-xs text-success">
            Authenticated as: {tokenValidation.userName}
          </p>
        )}
        {tokenValidation.checked && !tokenValidation.valid && tokenValidation.error && (
          <p className="mt-1 text-xs text-destructive">{tokenValidation.error}</p>
        )}
      </FormField>

      {/* Default Target Type */}
      <FormField
        label="Default Target"
        htmlFor="pb-target-type"
        help="Where to send notifications by default"
      >
        <Select
          id="pb-target-type"
          value={targetType}
          onChange={(e) => handleTargetTypeChange(e.target.value as PushbulletTargetType)}
          disabled={disabled}
        >
          <option value="all">All devices</option>
          <option value="device">Specific device</option>
          <option value="email">Email address</option>
          <option value="channel">Channel</option>
        </Select>
      </FormField>

      {/* Device Picker (when target is device) */}
      {targetType === 'device' && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={fetchDevices}
              disabled={disabled || !config.accessToken || isLoadingDevices}
            >
              {isLoadingDevices ? (
                <LoadingInline className="mr-2" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Fetch Devices
            </Button>
          </div>

          {devices.length > 0 && (
            <FormField label="Device" htmlFor="pb-device" required>
              <Select
                id="pb-device"
                value={config.defaultDeviceIden || ''}
                onChange={(e) => onChange({ ...config, defaultDeviceIden: e.target.value })}
                disabled={disabled}
              >
                <option value="">Select a device...</option>
                {devices.map((device) => (
                  <option key={device.iden} value={device.iden}>
                    {device.nickname} {device.model ? `(${device.model})` : ''}
                  </option>
                ))}
              </Select>
            </FormField>
          )}

          {devices.length === 0 && !isLoadingDevices && (
            <Alert variant="info">
              <AlertDescription>
                Click "Fetch Devices" to load your Pushbullet devices
              </AlertDescription>
            </Alert>
          )}
        </div>
      )}

      {/* Email Input (when target is email) */}
      {targetType === 'email' && (
        <FormField label="Email Address" htmlFor="pb-email" required>
          <Input
            id="pb-email"
            type="email"
            value={config.defaultEmail || ''}
            onChange={(e) => onChange({ ...config, defaultEmail: e.target.value })}
            placeholder="user@example.com"
            disabled={disabled}
          />
        </FormField>
      )}

      {/* Channel Tag Input (when target is channel) */}
      {targetType === 'channel' && (
        <FormField
          label="Channel Tag"
          htmlFor="pb-channel"
          required
          help="The channel's tag (not display name)"
        >
          <Input
            id="pb-channel"
            value={config.defaultChannelTag || ''}
            onChange={(e) => onChange({ ...config, defaultChannelTag: e.target.value })}
            placeholder="my-channel"
            disabled={disabled}
          />
        </FormField>
      )}
    </div>
  )
}
