import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { Select } from '@/components/ui/select'
import type { ActionRow } from '@/features/rules/builder'
import { AlarmArmActionFields } from '@/features/rules/components/then/AlarmArmActionFields'
import { HaCallServiceActionFields } from '@/features/rules/components/then/HaCallServiceActionFields'
import { Zigbee2mqttLightActionFields } from '@/features/rules/components/then/Zigbee2mqttLightActionFields'
import { Zigbee2mqttSetValueActionFields } from '@/features/rules/components/then/Zigbee2mqttSetValueActionFields'
import { Zigbee2mqttSwitchActionFields } from '@/features/rules/components/then/Zigbee2mqttSwitchActionFields'
import { ZwavejsSetValueActionFields } from '@/features/rules/components/then/ZwavejsSetValueActionFields'

type Props = {
  action: ActionRow
  actionsCount: number
  isSaving: boolean
  entityIdOptions: string[]
  pickerValue: string
  setPickerValue: (next: string) => void
  onRemove: () => void
  onChangeType: (nextType: ActionRow['type']) => void
  onUpdate: (updater: (prev: ActionRow) => ActionRow) => void
  updateHaActionTargetEntityIds: (actionId: string, nextEntityIds: string[]) => void
}

export function ThenActionRow({
  action,
  actionsCount,
  isSaving,
  entityIdOptions,
  pickerValue,
  setPickerValue,
  onRemove,
  onChangeType,
  onUpdate,
  updateHaActionTargetEntityIds,
}: Props) {
  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">Action</div>
        <Button type="button" variant="outline" disabled={actionsCount <= 1} onClick={onRemove}>
          Remove
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Type <HelpTip className="ml-1" content="Alarm actions change alarm state. call_service triggers a Home Assistant service call." />
          </label>
          <Select size="sm" value={action.type} onChange={(e) => onChangeType(e.target.value as ActionRow['type'])} disabled={isSaving}>
            <option value="alarm_trigger">Alarm trigger</option>
            <option value="alarm_disarm">Alarm disarm</option>
            <option value="alarm_arm">Alarm arm</option>
            <option value="ha_call_service">Home Assistant call_service</option>
            <option value="zwavejs_set_value">Z-Wave JS set_value</option>
            <option value="zigbee2mqtt_set_value">Zigbee2MQTT set value</option>
            <option value="zigbee2mqtt_switch">Zigbee2MQTT switch</option>
            <option value="zigbee2mqtt_light">Zigbee2MQTT light</option>
          </Select>
        </div>

        {action.type === 'alarm_arm' ? (
          <AlarmArmActionFields mode={action.mode} onChangeMode={(mode) => onUpdate((a) => (a.type === 'alarm_arm' ? { ...a, mode } : a))} />
        ) : null}

        {action.type === 'ha_call_service' ? (
          <HaCallServiceActionFields
            actionId={action.id}
            domain={action.domain}
            service={action.service}
            targetEntityIds={action.targetEntityIds}
            serviceDataJson={action.serviceDataJson}
            isSaving={isSaving}
            entityIdOptions={entityIdOptions}
            pickerValue={pickerValue}
            setPickerValue={setPickerValue}
            onChange={(patch) => onUpdate((a) => (a.type === 'ha_call_service' ? { ...a, ...patch } : a))}
            updateHaActionTargetEntityIds={updateHaActionTargetEntityIds}
          />
        ) : null}

        {action.type === 'zwavejs_set_value' ? (
          <ZwavejsSetValueActionFields
            nodeId={action.nodeId}
            commandClass={action.commandClass}
            endpoint={action.endpoint}
            property={action.property}
            propertyKey={action.propertyKey}
            valueJson={action.valueJson}
            onChange={(patch) => onUpdate((a) => (a.type === 'zwavejs_set_value' ? { ...a, ...patch } : a))}
          />
        ) : null}

        {action.type === 'zigbee2mqtt_set_value' ? (
          <Zigbee2mqttSetValueActionFields
            entityId={action.entityId}
            valueJson={action.valueJson}
            isSaving={isSaving}
            entityIdOptions={entityIdOptions}
            onChange={(patch) => onUpdate((a) => (a.type === 'zigbee2mqtt_set_value' ? { ...a, ...patch } : a))}
          />
        ) : null}

        {action.type === 'zigbee2mqtt_switch' ? (
          <Zigbee2mqttSwitchActionFields
            entityId={action.entityId}
            state={action.state}
            isSaving={isSaving}
            entityIdOptions={entityIdOptions}
            onChange={(patch) => onUpdate((a) => (a.type === 'zigbee2mqtt_switch' ? { ...a, ...patch } : a))}
          />
        ) : null}

        {action.type === 'zigbee2mqtt_light' ? (
          <Zigbee2mqttLightActionFields
            entityId={action.entityId}
            state={action.state}
            brightness={action.brightness}
            isSaving={isSaving}
            entityIdOptions={entityIdOptions}
            onChange={(patch) => onUpdate((a) => (a.type === 'zigbee2mqtt_light' ? { ...a, ...patch } : a))}
          />
        ) : null}
      </div>
    </div>
  )
}
