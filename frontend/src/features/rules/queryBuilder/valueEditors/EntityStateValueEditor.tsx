/**
 * Custom value editor for entity_state condition
 * Provides entity picker + state value input
 */
import { useId } from 'react'
import type { ValueEditorProps } from 'react-querybuilder'
import type { EntitySource, EntityStateValue, ValueEditorContext } from '../types'
import { Checkbox } from '@/components/ui/checkbox'
import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { EntityPicker } from '../EntityPicker'
import { getSuggestionsForDomain } from './domainStateSuggestions'

interface EntityStateValueEditorProps extends ValueEditorProps {
  context?: ValueEditorContext
  sourceFilter?: EntitySource
}

export function EntityStateValueEditor({
  value,
  handleOnChange,
  disabled,
  context,
  sourceFilter = 'all',
}: EntityStateValueEditorProps) {
  const currentValue = (value as EntityStateValue) || { entityId: '', equals: 'on' }
  const entities = context?.entities || []

  const selectedEntity = entities.find((e) => e.entityId === currentValue.entityId)
  const equalsListId = useId()
  const changedSinceId = useId()
  const suggestions = getSuggestionsForDomain(selectedEntity?.domain)

  // ADR-0108 (revision): only Home Assistant keeps a change-only `last_changed`
  // (Zigbee2MQTT stamps it on every report, Z-Wave JS live updates never write
  // it), so the option is offered for HA entities only.
  const supportsChangedSince =
    sourceFilter === 'home_assistant' ||
    (sourceFilter === 'all' && selectedEntity?.source === 'home_assistant')

  const handleEntityChange = (entityId: string) => {
    handleOnChange({ ...currentValue, entityId } as EntityStateValue)
  }

  const handleEqualsChange = (equals: string) => {
    handleOnChange({ ...currentValue, equals } as EntityStateValue)
  }

  // ADR-0108: opt this condition into "ignore state set before the alarm's last transition".
  const handleChangedSinceChange = (changedSinceAlarmTransition: boolean) => {
    handleOnChange({ ...currentValue, changedSinceAlarmTransition } as EntityStateValue)
  }

  return (
    <div className="flex items-center gap-2">
      <EntityPicker
        value={currentValue.entityId}
        onChange={handleEntityChange}
        entities={entities}
        disabled={disabled}
        sourceFilter={sourceFilter}
      />

      {/* Equals label */}
      <span className="text-sm text-muted-foreground">equals</span>

      {/* State value input — editable datalist: pick a canonical domain
          state or type a custom value. */}
      <DatalistInput
        listId={equalsListId}
        options={suggestions}
        type="text"
        value={currentValue.equals}
        onChange={(e) => handleEqualsChange(e.target.value)}
        disabled={disabled}
        placeholder="on"
        className="h-8 w-44"
      />

      {supportsChangedSince && (
        <>
          <label
            htmlFor={changedSinceId}
            className="flex items-center gap-1.5 whitespace-nowrap text-sm text-muted-foreground"
          >
            <Checkbox
              id={changedSinceId}
              checked={currentValue.changedSinceAlarmTransition === true}
              onChange={(e) => handleChangedSinceChange(e.target.checked)}
              disabled={disabled}
            />
            Only after alarm state change
          </label>
          <HelpTip
            label="About 'Only after alarm state change'"
            content={
              <span className="block max-w-xs">
                When ticked, this condition ignores a sensor that was already in this state when the alarm
                entered its current state (for example a door left open before arming), so arming does not
                trigger immediately. The sensor counts again the next time it changes into this state.
                Available for Home Assistant entities only.
              </span>
            }
          />
        </>
      )}
    </div>
  )
}
