/**
 * Custom value editor for entity_state condition
 * Provides entity picker + state value input
 */
import { useId } from 'react'
import type { ValueEditorProps } from 'react-querybuilder'
import type { EntitySource, EntityStateValue, ValueEditorContext } from '../types'
import { DatalistInput } from '@/components/ui/datalist-input'
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
  const suggestions = getSuggestionsForDomain(selectedEntity?.domain)

  const handleEntityChange = (entityId: string) => {
    handleOnChange({ ...currentValue, entityId } as EntityStateValue)
  }

  const handleEqualsChange = (equals: string) => {
    handleOnChange({ ...currentValue, equals } as EntityStateValue)
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
    </div>
  )
}
