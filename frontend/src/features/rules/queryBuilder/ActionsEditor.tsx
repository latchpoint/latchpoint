/**
 * Actions editor for the rule builder
 * Provides a simple interface for selecting actions to execute when rule fires
 */
import type {
  ActionNode,
  HaCallServiceAction,
  ZwavejsSetValueAction,
  SendNotificationAction,
  Zigbee2mqttSetValueAction,
} from '@/types/ruleDefinition'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { HelpTip } from '@/components/ui/help-tip'
import { cn } from '@/lib/utils'
import { Trash2, ChevronDown, ChevronUp } from 'lucide-react'
import { useState, useMemo } from 'react'
import { useHomeAssistantStatus, useHomeAssistantNotifyServices } from '@/hooks/useHomeAssistant'
import { useEnabledNotificationProviders } from '@/features/notifications/hooks/useNotificationProviders'
import { useZwavejsStatusQuery } from '@/hooks/useZwavejs'
import { useZigbee2mqttStatusQuery } from '@/hooks/useZigbee2mqtt'
import { HA_SYSTEM_PROVIDER_ID } from '@/lib/constants'

const ACTION_TYPES = [
  { value: 'alarm_trigger', label: 'Trigger Alarm', requiresConfig: null },
  { value: 'alarm_disarm', label: 'Disarm Alarm', requiresConfig: null },
  { value: 'alarm_arm', label: 'Arm Alarm', requiresConfig: null },
  { value: 'send_notification', label: 'Send Notification', requiresConfig: 'notifications' },
  { value: 'ha_call_service', label: 'HA Call Service', requiresConfig: 'ha' },
  { value: 'zwavejs_set_value', label: 'Z-Wave Set Value', requiresConfig: 'zwavejs' },
  { value: 'zigbee2mqtt_set_value', label: 'Zigbee2MQTT Set Value', requiresConfig: 'zigbee2mqtt' },
] as const

const ARM_MODES = [
  { value: 'armed_home', label: 'Armed Home' },
  { value: 'armed_away', label: 'Armed Away' },
  { value: 'armed_night', label: 'Armed Night' },
  { value: 'armed_vacation', label: 'Armed Vacation' },
] as const

interface ActionsEditorProps {
  actions: ActionNode[]
  onChange: (actions: ActionNode[]) => void
  disabled?: boolean
}

interface ActionRowProps {
  action: ActionNode & { _id?: string }
  index: number
  onUpdate: (action: ActionNode) => void
  onRemove: () => void
  disabled?: boolean
  canRemove: boolean
  availableActionTypes: typeof ACTION_TYPES[number][]
}

function ActionRow({ action, onUpdate, onRemove, disabled, canRemove, availableActionTypes }: ActionRowProps) {
  const actionType = action.type

  // Check if this action type has expandable details
  const hasDetails =
    actionType === 'ha_call_service' ||
    actionType === 'zwavejs_set_value' ||
    actionType === 'zigbee2mqtt_set_value' ||
    actionType === 'send_notification'

  const [expanded, setExpanded] = useState(hasDetails)

  const handleTypeChange = (newType: string) => {
    // Determine if the new action type has expandable details
    const newTypeHasDetails =
      newType === 'ha_call_service' ||
      newType === 'zwavejs_set_value' ||
      newType === 'zigbee2mqtt_set_value' ||
      newType === 'send_notification'

    // Auto-expand when switching to an action type with details
    if (newTypeHasDetails) {
      setExpanded(true)
    }

    switch (newType) {
      case 'alarm_trigger':
        onUpdate({ type: 'alarm_trigger' })
        break
      case 'alarm_disarm':
        onUpdate({ type: 'alarm_disarm' })
        break
      case 'alarm_arm':
        onUpdate({ type: 'alarm_arm', mode: 'armed_away' })
        break
      case 'send_notification':
        onUpdate({
          type: 'send_notification',
          providerId: '',
          message: '',
          title: '',
        })
        break
      case 'ha_call_service':
        onUpdate({
          type: 'ha_call_service',
          action: '',
          target: { entityIds: [] },
          data: {},
        })
        break
      case 'zwavejs_set_value':
        onUpdate({
          type: 'zwavejs_set_value',
          nodeId: 0,
          valueId: {
            commandClass: 0,
            property: '',
          },
          value: null,
        })
        break
      case 'zigbee2mqtt_set_value':
        onUpdate({
          type: 'zigbee2mqtt_set_value',
          entityId: '',
          value: null,
        })
        break
    }
  }

  return (
    <div
      className={cn(
        'rounded-md border bg-muted/30',
        disabled && 'opacity-60'
      )}
    >
      <div className="flex items-center gap-2 p-2">
        {/* Action type selector */}
        <Select
          value={actionType}
          onChange={(e) => handleTypeChange(e.target.value)}
          disabled={disabled}
          size="sm"
          className="min-w-[160px]"
        >
          {availableActionTypes.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </Select>

        {/* Mode selector for alarm_arm */}
        {actionType === 'alarm_arm' && (
          <>
            <span className="text-sm text-muted-foreground">to</span>
            <Select
              value={(action as { type: 'alarm_arm'; mode: string }).mode}
              onChange={(e) =>
                onUpdate({
                  type: 'alarm_arm',
                  mode: e.target.value as 'armed_home' | 'armed_away' | 'armed_night' | 'armed_vacation',
                })
              }
              disabled={disabled}
              size="sm"
              className="min-w-[140px]"
            >
              {ARM_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </Select>
          </>
        )}

        {/* Quick summary for send_notification actions */}
        {actionType === 'send_notification' && (
          <SendNotificationSummary action={action as SendNotificationAction} />
        )}

        {/* Quick summary for HA call service */}
        {actionType === 'ha_call_service' && (
          <span className="text-sm text-muted-foreground">
            {(action as HaCallServiceAction).action || 'Configure service'}
          </span>
        )}

        {/* Quick summary for Z-Wave set value */}
        {actionType === 'zwavejs_set_value' && (
          <span className="text-sm text-muted-foreground">
            {(action as ZwavejsSetValueAction).nodeId ? `Node ${(action as ZwavejsSetValueAction).nodeId}` : 'Configure node'}
          </span>
        )}

        {/* Quick summary for Zigbee2MQTT set value */}
        {actionType === 'zigbee2mqtt_set_value' && (
          <span className="text-sm text-muted-foreground">
            {(action as Zigbee2mqttSetValueAction).entityId || 'Select entity'}
          </span>
        )}

        {/* Expand/collapse button for complex actions */}
        {hasDetails && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(!expanded)}
            className="h-8 w-8 p-0"
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        )}

        {/* Remove button */}
        <div className="ml-auto">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onRemove}
            disabled={disabled || !canRemove}
            className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Expanded details for send_notification actions */}
      {expanded && actionType === 'send_notification' && (
        <SendNotificationFields
          action={action as SendNotificationAction}
          onUpdate={onUpdate}
          disabled={disabled}
        />
      )}

      {/* Expanded details for ha_call_service */}
      {expanded && actionType === 'ha_call_service' && (
        <HaCallServiceFields
          action={action as HaCallServiceAction}
          onUpdate={onUpdate}
          disabled={disabled}
        />
      )}

      {/* Expanded details for zwavejs_set_value */}
      {expanded && actionType === 'zwavejs_set_value' && (
        <ZwavejsSetValueFields
          action={action as ZwavejsSetValueAction}
          onUpdate={onUpdate}
          disabled={disabled}
        />
      )}

      {/* Expanded details for zigbee2mqtt_set_value */}
      {expanded && actionType === 'zigbee2mqtt_set_value' && (
        <Zigbee2mqttSetValueFields
          action={action as Zigbee2mqttSetValueAction}
          onUpdate={onUpdate}
          disabled={disabled}
        />
      )}
    </div>
  )
}

/**
 * Fields for ha_call_service action
 * Uses "action" field in domain.service format (e.g., "notify.notify")
 */
function HaCallServiceFields({
  action,
  onUpdate,
  disabled,
}: {
  action: HaCallServiceAction
  onUpdate: (action: ActionNode) => void
  disabled?: boolean
}) {
  // Parse action field (e.g., "notify.notify") into domain and service for editing
  const actionStr = action.action || ''
  const dotIndex = actionStr.indexOf('.')
  const domain = dotIndex > 0 ? actionStr.slice(0, dotIndex) : actionStr
  const service = dotIndex > 0 ? actionStr.slice(dotIndex + 1) : ''

  const [dataText, setDataText] = useState(() =>
    JSON.stringify(action.data || {}, null, 2)
  )
  const [dataError, setDataError] = useState<string | null>(null)

  const handleDomainChange = (newDomain: string) => {
    onUpdate({ ...action, action: `${newDomain}.${service}` })
  }

  const handleServiceChange = (newService: string) => {
    onUpdate({ ...action, action: `${domain}.${newService}` })
  }

  const handleDataChange = (text: string) => {
    setDataText(text)
    try {
      const parsed = JSON.parse(text || '{}')
      setDataError(null)
      onUpdate({
        ...action,
        data: parsed,
      })
    } catch {
      setDataError('Invalid JSON')
    }
  }

  return (
    <div className="border-t p-3 space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Domain</label>
          <Input
            value={domain}
            onChange={(e) => handleDomainChange(e.target.value)}
            placeholder="e.g., notify, light, switch"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Service</label>
          <Input
            value={service}
            onChange={(e) => handleServiceChange(e.target.value)}
            placeholder="e.g., notify, turn_on, turn_off"
            disabled={disabled}
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Target Entity IDs (comma-separated)
        </label>
        <Input
          value={action.target?.entityIds?.join(', ') || ''}
          onChange={(e) => {
            const entityIds = e.target.value
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
            onUpdate({
              ...action,
              target: { entityIds },
            })
          }}
          placeholder="e.g., light.living_room, switch.kitchen"
          disabled={disabled}
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Data (JSON){' '}
          <HelpTip content="Additional data to pass to the action" className="ml-1" />
        </label>
        <Textarea
          value={dataText}
          onChange={(e) => handleDataChange(e.target.value)}
          placeholder='{"message": "Alarm triggered!"}'
          disabled={disabled}
          className="min-h-[80px] font-mono text-xs"
        />
        {dataError && (
          <p className="text-xs text-destructive">{dataError}</p>
        )}
      </div>
    </div>
  )
}

/**
 * Summary component for send_notification actions
 */
function SendNotificationSummary({ action }: { action: SendNotificationAction }) {
  const providersQuery = useEnabledNotificationProviders()

  // Handle HA system provider
  if (action.providerId === HA_SYSTEM_PROVIDER_ID) {
    const service = action.data?.service as string
    if (service) {
      return <span className="text-sm text-muted-foreground">via {service}</span>
    }
    return <span className="text-sm text-destructive">No service selected</span>
  }

  const provider = providersQuery.data?.find((p) => p.id === action.providerId)
  if (provider) {
    return <span className="text-sm text-muted-foreground">via {provider.name}</span>
  }
  return <span className="text-sm text-destructive">No provider selected</span>
}

/**
 * Fields for send_notification action (new provider-based)
 */
function SendNotificationFields({
  action,
  onUpdate,
  disabled,
}: {
  action: SendNotificationAction
  onUpdate: (action: ActionNode) => void
  disabled?: boolean
}) {
  const providersQuery = useEnabledNotificationProviders()
  const haStatus = useHomeAssistantStatus()
  const haNotifyServices = useHomeAssistantNotifyServices()

  const providers = providersQuery.data ?? []
  const isHaConfigured = haStatus.data?.configured ?? false
  const isHaProvider = action.providerId === HA_SYSTEM_PROVIDER_ID
  const haServices = haNotifyServices.data ?? []

  // Get current HA service from action.data
  const currentHaService = isHaProvider ? (action.data?.service as string) || '' : ''

  const handleProviderChange = (providerId: string) => {
    if (providerId === HA_SYSTEM_PROVIDER_ID) {
      // When switching to HA, initialize data with service
      onUpdate({ ...action, providerId, data: { service: '' } })
    } else {
      // When switching away from HA, clear data
      onUpdate({ ...action, providerId, data: undefined })
    }
  }

  const handleHaServiceChange = (service: string) => {
    onUpdate({ ...action, data: { ...action.data, service } })
  }

  return (
    <div className="border-t p-3 space-y-3">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Notification Provider{' '}
          <HelpTip content="Select a configured notification provider" className="ml-1" />
        </label>
        <Select
          value={action.providerId}
          onChange={(e) => handleProviderChange(e.target.value)}
          disabled={disabled}
        >
          <option value="">Select a provider...</option>
          {isHaConfigured && (
            <option value={HA_SYSTEM_PROVIDER_ID}>Home Assistant</option>
          )}
          {providers.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name}
            </option>
          ))}
        </Select>
        {providers.length === 0 && !isHaConfigured && !providersQuery.isLoading && (
          <p className="text-xs text-muted-foreground">
            No providers configured. Go to Settings &gt; Notifications to add one.
          </p>
        )}
      </div>

      {/* Show HA service picker when HA provider is selected */}
      {isHaProvider && (
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Notify Service{' '}
            <HelpTip content="Home Assistant notify service (e.g., notify.mobile_app_iphone)" className="ml-1" />
          </label>
          <Select
            value={currentHaService}
            onChange={(e) => handleHaServiceChange(e.target.value)}
            disabled={disabled}
          >
            <option value="">Select a service...</option>
            {haServices.map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </Select>
          {haNotifyServices.isLoading && (
            <p className="text-xs text-muted-foreground">Loading services...</p>
          )}
          {!haNotifyServices.isLoading && haServices.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No notify services found in Home Assistant.
            </p>
          )}
        </div>
      )}

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Message{' '}
          <HelpTip content="The notification message content" className="ml-1" />
        </label>
        <Textarea
          value={action.message}
          onChange={(e) => onUpdate({ ...action, message: e.target.value })}
          placeholder="Alarm triggered! Check your security cameras."
          disabled={disabled}
          className="min-h-[60px]"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Title (optional){' '}
          <HelpTip content="The notification title" className="ml-1" />
        </label>
        <Input
          value={action.title || ''}
          onChange={(e) => onUpdate({ ...action, title: e.target.value || undefined })}
          placeholder="Security Alert"
          disabled={disabled}
        />
      </div>
    </div>
  )
}

/**
 * Fields for zwavejs_set_value action
 */
function ZwavejsSetValueFields({
  action,
  onUpdate,
  disabled,
}: {
  action: ZwavejsSetValueAction
  onUpdate: (action: ActionNode) => void
  disabled?: boolean
}) {
  const [valueText, setValueText] = useState(() => {
    const val = action.value
    if (val === null || val === undefined) return ''
    if (typeof val === 'object') return JSON.stringify(val)
    return String(val)
  })

  const handleValueChange = (text: string) => {
    setValueText(text)
    // Try to parse as JSON, otherwise use as string/boolean/number
    let parsedValue: unknown = text
    if (text === 'true') parsedValue = true
    else if (text === 'false') parsedValue = false
    else if (!isNaN(Number(text)) && text.trim() !== '') parsedValue = Number(text)
    else {
      try {
        parsedValue = JSON.parse(text)
      } catch {
        parsedValue = text
      }
    }
    onUpdate({ ...action, value: parsedValue })
  }

  return (
    <div className="border-t p-3 space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Node ID{' '}
            <HelpTip content="The Z-Wave node ID of the device. Find this in the Z-Wave JS UI or Home Assistant Z-Wave integration." className="ml-1" />
          </label>
          <Input
            type="number"
            value={action.nodeId || ''}
            onChange={(e) => onUpdate({ ...action, nodeId: parseInt(e.target.value) || 0 })}
            placeholder="e.g., 5"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Command Class{' '}
            <HelpTip content="Z-Wave command class number. Common: 37 (Binary Switch), 38 (Multilevel Switch), 113 (Notification), 114 (Manufacturer Specific)." className="ml-1" />
          </label>
          <Input
            type="number"
            value={action.valueId.commandClass || ''}
            onChange={(e) =>
              onUpdate({
                ...action,
                valueId: { ...action.valueId, commandClass: parseInt(e.target.value) || 0 },
              })
            }
            placeholder="e.g., 37"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Endpoint{' '}
            <HelpTip content="Optional endpoint index for multi-channel devices. Leave empty for single-channel devices." className="ml-1" />
          </label>
          <Input
            type="number"
            value={action.valueId.endpoint ?? ''}
            onChange={(e) => {
              const val = e.target.value
              onUpdate({
                ...action,
                valueId: {
                  ...action.valueId,
                  endpoint: val === '' ? undefined : parseInt(val) || 0,
                },
              })
            }}
            placeholder="Optional"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Property{' '}
            <HelpTip content="The property name to set. Common: 'targetValue' for switches, 'currentValue' for sensors." className="ml-1" />
          </label>
          <Input
            value={String(action.valueId.property || '')}
            onChange={(e) =>
              onUpdate({
                ...action,
                valueId: { ...action.valueId, property: e.target.value },
              })
            }
            placeholder="e.g., targetValue"
            disabled={disabled}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Property Key{' '}
            <HelpTip content="Optional sub-property key. Used for properties with multiple values like color components." className="ml-1" />
          </label>
          <Input
            value={action.valueId.propertyKey != null ? String(action.valueId.propertyKey) : ''}
            onChange={(e) => {
              const val = e.target.value
              onUpdate({
                ...action,
                valueId: {
                  ...action.valueId,
                  propertyKey: val === '' ? undefined : val,
                },
              })
            }}
            placeholder="Optional"
            disabled={disabled}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Value{' '}
            <HelpTip content="The value to set. Use true/false for switches, numbers for dimmers (0-99), or JSON for complex values." className="ml-1" />
          </label>
          <Input
            value={valueText}
            onChange={(e) => handleValueChange(e.target.value)}
            placeholder="true, false, 255, or JSON"
            disabled={disabled}
          />
        </div>
      </div>
    </div>
  )
}

function Zigbee2mqttSetValueFields({
  action,
  onUpdate,
  disabled,
}: {
  action: Zigbee2mqttSetValueAction
  onUpdate: (action: ActionNode) => void
  disabled?: boolean
}) {
  const [valueText, setValueText] = useState(() =>
    action.value === null || action.value === undefined ? '' : JSON.stringify(action.value, null, 2)
  )
  const [valueError, setValueError] = useState<string | null>(null)

  const handleValueChange = (text: string) => {
    setValueText(text)
    try {
      const parsed = JSON.parse(text || 'null')
      setValueError(null)
      onUpdate({ ...action, value: parsed })
    } catch {
      setValueError('Invalid JSON')
    }
  }

  return (
    <div className="border-t p-3 space-y-3">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Entity ID</label>
        <Input
          value={action.entityId}
          onChange={(e) => onUpdate({ ...action, entityId: e.target.value })}
          placeholder="e.g., z2m_switch.0x..._state"
          disabled={disabled}
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Value (JSON)</label>
        <Textarea
          value={valueText}
          onChange={(e) => handleValueChange(e.target.value)}
          placeholder={'true\n"ON"\n200'}
          disabled={disabled}
          className="min-h-[80px] font-mono text-xs"
        />
        {valueError && <p className="text-xs text-destructive">{valueError}</p>}
      </div>
    </div>
  )
}

export function ActionsEditor({ actions, onChange, disabled = false }: ActionsEditorProps) {
  // Check what services are configured
  const haStatus = useHomeAssistantStatus()
  const zwavejsStatus = useZwavejsStatusQuery()
  const zigbee2mqttStatus = useZigbee2mqttStatusQuery()
  const providersQuery = useEnabledNotificationProviders()

  const isHaConfigured = haStatus.data?.configured ?? false
  const isZwavejsConfigured = zwavejsStatus.data?.configured && zwavejsStatus.data?.enabled
  const isZigbee2mqttConfigured = zigbee2mqttStatus.data?.enabled ?? false
  const hasNotificationProviders = (providersQuery.data?.length ?? 0) > 0 || isHaConfigured

  // Filter action types based on what's configured
  const availableActionTypes = useMemo(() => {
    return ACTION_TYPES.filter((type) => {
      if (type.requiresConfig === null) return true
      if (type.requiresConfig === 'ha') return isHaConfigured
      if (type.requiresConfig === 'zwavejs') return isZwavejsConfigured
      if (type.requiresConfig === 'zigbee2mqtt') return isZigbee2mqttConfigured
      if (type.requiresConfig === 'notifications') return hasNotificationProviders
      return true
    })
  }, [isHaConfigured, isZwavejsConfigured, isZigbee2mqttConfigured, hasNotificationProviders])

  // Ensure actions have internal IDs for React keys
  const actionsWithIds = actions.map((action, i) => ({
    ...action,
    _id: `action-${i}`,
  }))

  const handleAddAction = () => {
    onChange([...actions, { type: 'alarm_trigger' }])
  }

  const handleUpdateAction = (index: number, action: ActionNode) => {
    const newActions = [...actions]
    newActions[index] = action
    onChange(newActions)
  }

  const handleRemoveAction = (index: number) => {
    const newActions = actions.filter((_, i) => i !== index)
    onChange(newActions)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Then{' '}
          <HelpTip
            className="ml-1"
            content="Actions to execute when the conditions are met. Multiple actions run in order."
          />
        </CardTitle>
        <CardDescription>What happens when the rule fires</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {actionsWithIds.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
            No actions configured. Add an action to define what happens when the rule fires.
          </div>
        ) : (
          <div className="space-y-2">
            {actionsWithIds.map((action, index) => (
              <ActionRow
                key={action._id}
                action={action}
                index={index}
                onUpdate={(updated) => handleUpdateAction(index, updated)}
                onRemove={() => handleRemoveAction(index)}
                disabled={disabled}
                canRemove={actionsWithIds.length > 1}
                availableActionTypes={availableActionTypes}
              />
            ))}
          </div>
        )}

        <Button type="button" variant="outline" onClick={handleAddAction} disabled={disabled}>
          + Add Action
        </Button>
      </CardContent>
    </Card>
  )
}
