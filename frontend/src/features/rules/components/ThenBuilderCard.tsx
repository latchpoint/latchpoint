import type React from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { uniqueId, type ActionRow } from '@/features/rules/builder'
import { ThenActionRow } from '@/features/rules/components/then/ThenActionRow'

type Props = {
  actions: ActionRow[]
  setActions: React.Dispatch<React.SetStateAction<ActionRow[]>>
  isSaving: boolean
  entityIdOptions: string[]

  targetEntityPickerByActionId: Record<string, string>
  setTargetEntityPickerByActionId: React.Dispatch<React.SetStateAction<Record<string, string>>>
  updateHaActionTargetEntityIds: (actionId: string, nextEntityIds: string[]) => void
}

export function ThenBuilderCard({
  actions,
  setActions,
  isSaving,
  entityIdOptions,
  targetEntityPickerByActionId,
  setTargetEntityPickerByActionId,
  updateHaActionTargetEntityIds,
}: Props) {
  const changeActionType = (actionId: string, type: ActionRow['type']) => {
    setActions((prev) =>
      prev.map((row) => {
        if (row.id !== actionId) return row
        if (type === 'alarm_disarm') return { id: row.id, type }
        if (type === 'alarm_trigger') return { id: row.id, type }
        if (type === 'alarm_arm') return { id: row.id, type, mode: 'armed_away' }
        if (type === 'zwavejs_set_value')
          return {
            id: row.id,
            type,
            nodeId: '',
            commandClass: '',
            endpoint: '0',
            property: '',
            propertyKey: '',
            valueJson: 'true',
          }
        if (type === 'zigbee2mqtt_set_value')
          return {
            id: row.id,
            type,
            entityId: '',
            valueJson: 'true',
          }
        if (type === 'zigbee2mqtt_switch')
          return {
            id: row.id,
            type,
            entityId: '',
            state: 'on',
          }
        if (type === 'zigbee2mqtt_light')
          return {
            id: row.id,
            type,
            entityId: '',
            state: 'on',
            brightness: '',
          }
        return {
          id: row.id,
          type,
          domain: 'notify',
          service: '',
          targetEntityIds: '',
          serviceDataJson: '{\n  "message": "Rule fired"\n}',
        }
      }) as ActionRow[]
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Then <HelpTip className="ml-1" content="The action(s) to execute when the rule matches. Multiple actions run in order." />
        </CardTitle>
        <CardDescription>Actions to run when the condition matches.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          {actions.map((action) => (
            <ThenActionRow
              key={action.id}
              action={action}
              actionsCount={actions.length}
              isSaving={isSaving}
              entityIdOptions={entityIdOptions}
              pickerValue={targetEntityPickerByActionId[action.id] ?? ''}
              setPickerValue={(next) => setTargetEntityPickerByActionId((prev) => ({ ...prev, [action.id]: next }))}
              onRemove={() => setActions((prev) => prev.filter((x) => x.id !== action.id))}
              onChangeType={(nextType) => changeActionType(action.id, nextType)}
              onUpdate={(updater) => setActions((prev) => prev.map((row) => (row.id === action.id ? updater(row) : row)) as ActionRow[])}
              updateHaActionTargetEntityIds={updateHaActionTargetEntityIds}
            />
          ))}
        </div>

        <Button type="button" variant="outline" onClick={() => setActions((prev) => [...prev, { id: uniqueId(), type: 'alarm_trigger' }])}>
          Add action
        </Button>
      </CardContent>
    </Card>
  )
}
