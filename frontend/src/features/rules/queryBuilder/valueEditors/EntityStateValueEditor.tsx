/**
 * Custom value editor for entity_state condition
 * Provides entity picker + state value input
 */
import { useState, useMemo } from 'react'
import type { ValueEditorProps } from 'react-querybuilder'
import type { EntityStateValue } from '../types'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface EntityOption {
  entityId: string
  name: string
  domain: string
  source?: string
}

// Entity source filter type
export type EntitySourceFilter = 'home_assistant' | 'zwavejs' | 'zigbee2mqtt' | 'all'

interface EntityStateValueEditorProps extends ValueEditorProps {
  context?: {
    entities?: EntityOption[]
  }
  sourceFilter?: EntitySourceFilter
}

export function EntityStateValueEditor({
  value,
  handleOnChange,
  disabled,
  context,
  sourceFilter = 'all',
}: EntityStateValueEditorProps) {
  const currentValue = (value as EntityStateValue) || { entityId: '', equals: 'on' }
  const [searchText, setSearchText] = useState('')
  const [isOpen, setIsOpen] = useState(false)

  const entities = context?.entities || []

  // Filter entities by source first, then by search text
  const filteredEntities = useMemo(() => {
    // First filter by source
    const sourceFiltered = sourceFilter === 'all'
      ? entities
      : entities.filter((e) => e.source === sourceFilter)

    // Then filter by search text
    if (!searchText.trim()) return sourceFiltered.slice(0, 50)
    const search = searchText.toLowerCase()
    return sourceFiltered
      .filter(
        (e) =>
          e.entityId.toLowerCase().includes(search) ||
          e.name.toLowerCase().includes(search)
      )
      .slice(0, 50)
  }, [entities, searchText, sourceFilter])

  const selectedEntity = entities.find((e) => e.entityId === currentValue.entityId)

  const handleEntitySelect = (entityId: string) => {
    handleOnChange({ ...currentValue, entityId } as EntityStateValue)
    setIsOpen(false)
    setSearchText('')
  }

  const handleEqualsChange = (equals: string) => {
    handleOnChange({ ...currentValue, equals } as EntityStateValue)
  }

  return (
    <div className="flex items-center gap-2">
      {/* Entity picker */}
      <div className="relative min-w-[200px]">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setIsOpen(!isOpen)}
          className={cn(
            'flex h-8 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm',
            'hover:bg-accent hover:text-accent-foreground',
            disabled && 'cursor-not-allowed opacity-50'
          )}
        >
          <span className="truncate">
            {selectedEntity ? selectedEntity.entityId : 'Select entity...'}
          </span>
          <svg
            className="h-4 w-4 opacity-50"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>

        {isOpen && !disabled && (
          <div className="absolute z-50 mt-1 max-h-60 w-full min-w-[300px] overflow-hidden rounded-md border bg-popover shadow-md">
            <div className="p-2">
              <Input
                type="text"
                placeholder="Search entities..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                className="h-8"
                autoFocus
              />
            </div>
            <div className="max-h-48 overflow-y-auto">
              {filteredEntities.length === 0 ? (
                <div className="px-3 py-2 text-sm text-muted-foreground">
                  No entities found
                </div>
              ) : (
                filteredEntities.map((entity) => (
                  <button
                    key={entity.entityId}
                    type="button"
                    onClick={() => handleEntitySelect(entity.entityId)}
                    className={cn(
                      'flex w-full flex-col items-start px-3 py-1.5 text-left text-sm',
                      'hover:bg-accent hover:text-accent-foreground',
                      entity.entityId === currentValue.entityId && 'bg-accent'
                    )}
                  >
                    <span className="font-mono text-xs">{entity.entityId}</span>
                    {entity.name && entity.name !== entity.entityId && (
                      <span className="text-xs text-muted-foreground">{entity.name}</span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Equals label */}
      <span className="text-sm text-muted-foreground">equals</span>

      {/* State value input */}
      <Input
        type="text"
        value={currentValue.equals}
        onChange={(e) => handleEqualsChange(e.target.value)}
        disabled={disabled}
        placeholder="on"
        className="h-8 w-20"
      />
    </div>
  )
}
