/**
 * Pushbullet notification options for rule builder
 * Provides advanced options like URL, target override, and image URL
 */
import { useState, useCallback } from 'react'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { LoadingInline } from '@/components/ui/loading-inline'
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { notificationsService } from '@/services/notifications'
import type { PushbulletNotificationData, PushbulletDevice, PushbulletTargetType } from '@/types/notifications'

interface PushbulletNotificationOptionsProps {
  data: PushbulletNotificationData
  onChange: (data: PushbulletNotificationData) => void
  providerId: string
  disabled?: boolean
}

export function PushbulletNotificationOptions({
  data,
  onChange,
  providerId,
  disabled = false,
}: PushbulletNotificationOptionsProps) {
  const [expanded, setExpanded] = useState(false)
  const [devices, setDevices] = useState<PushbulletDevice[]>([])
  const [isLoadingDevices, setIsLoadingDevices] = useState(false)

  const targetOverrideType = data.targetOverride?.type || 'default'

  const fetchDevices = useCallback(async () => {
    if (!providerId) return

    setIsLoadingDevices(true)
    try {
      const fetchedDevices = await notificationsService.getPushbulletDevicesByProvider(providerId)
      setDevices(fetchedDevices)
    } catch {
      setDevices([])
    } finally {
      setIsLoadingDevices(false)
    }
  }, [providerId])

  const handleTargetOverrideChange = (type: string) => {
    if (type === 'default') {
      onChange({ ...data, targetOverride: undefined })
    } else {
      onChange({
        ...data,
        targetOverride: { type: type as PushbulletTargetType },
      })
    }
  }

  // Check if there are any advanced options set
  const hasAdvancedOptions = data.url || data.imageUrl || data.targetOverride

  return (
    <div className="border-t p-3">
      {/* Expandable header */}
      <button
        type="button"
        className="flex w-full items-center justify-between text-sm text-muted-foreground hover:text-foreground"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="flex items-center gap-2">
          Advanced Options
          {hasAdvancedOptions && !expanded && (
            <span className="text-xs text-primary">(configured)</span>
          )}
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="mt-3 space-y-3">
          {/* URL */}
          <FormField
            label="URL (opens on click)"
            htmlFor="pb-notif-url"
            size="compact"
            help="Link to open when user taps the notification"
          >
            <Input
              id="pb-notif-url"
              value={data.url || ''}
              onChange={(e) => onChange({ ...data, url: e.target.value || undefined })}
              placeholder="https://..."
              disabled={disabled}
            />
          </FormField>

          {/* Image URL */}
          <FormField
            label="Image URL"
            htmlFor="pb-notif-image"
            size="compact"
            help="Attach an image to the notification"
          >
            <Input
              id="pb-notif-image"
              value={data.imageUrl || ''}
              onChange={(e) => onChange({ ...data, imageUrl: e.target.value || undefined })}
              placeholder="https://example.com/image.jpg"
              disabled={disabled}
            />
          </FormField>

          {/* Target Override */}
          <FormField
            label="Target Override"
            htmlFor="pb-notif-target"
            size="compact"
            help="Override the provider's default target"
          >
            <Select
              id="pb-notif-target"
              value={targetOverrideType}
              onChange={(e) => handleTargetOverrideChange(e.target.value)}
              disabled={disabled}
            >
              <option value="default">Use provider default</option>
              <option value="all">All devices</option>
              <option value="device">Specific device</option>
              <option value="email">Email address</option>
            </Select>
          </FormField>

          {/* Device picker for target override */}
          {data.targetOverride?.type === 'device' && (
            <div className="space-y-2 pl-2">
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={fetchDevices}
                  disabled={disabled || isLoadingDevices}
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
                <Select
                  value={data.targetOverride.deviceIden || ''}
                  onChange={(e) =>
                    onChange({
                      ...data,
                      targetOverride: {
                        ...data.targetOverride!,
                        deviceIden: e.target.value || undefined,
                      },
                    })
                  }
                  disabled={disabled}
                  size="sm"
                >
                  <option value="">Select a device...</option>
                  {devices.map((device) => (
                    <option key={device.iden} value={device.iden}>
                      {device.nickname} {device.model ? `(${device.model})` : ''}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          )}

          {/* Email input for target override */}
          {data.targetOverride?.type === 'email' && (
            <div className="pl-2">
              <Input
                type="email"
                value={data.targetOverride.email || ''}
                onChange={(e) =>
                  onChange({
                    ...data,
                    targetOverride: {
                      ...data.targetOverride!,
                      email: e.target.value || undefined,
                    },
                  })
                }
                placeholder="user@example.com"
                disabled={disabled}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
