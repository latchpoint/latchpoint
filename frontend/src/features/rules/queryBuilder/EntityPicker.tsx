/**
 * Searchable dropdown for picking a single entity ID.
 * Shared between the WHEN entity_state value editor and the THEN call-service
 * action's target list.
 */
import { useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { EntityOption, EntitySource } from './types'

interface EntityPickerProps {
  value: string
  onChange: (entityId: string) => void
  entities: EntityOption[]
  disabled?: boolean
  sourceFilter?: EntitySource
  placeholder?: string
  className?: string
}

export function EntityPicker({
  value,
  onChange,
  entities,
  disabled,
  sourceFilter = 'all',
  placeholder = 'Select entity...',
  className,
}: EntityPickerProps) {
  const [searchText, setSearchText] = useState('')
  const [isOpen, setIsOpen] = useState(false)

  // Filter entities by source first, then by search text
  const filteredEntities = useMemo(() => {
    const sourceFiltered = sourceFilter === 'all'
      ? entities
      : entities.filter((e) => e.source === sourceFilter)

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

  // Look up the selected entity in the *unfiltered* list so saved values from a
  // different source still render their entityId in the trigger button.
  const selectedEntity = entities.find((e) => e.entityId === value)

  const handleSelect = (entityId: string) => {
    onChange(entityId)
    setIsOpen(false)
    setSearchText('')
  }

  return (
    <div className={cn('relative min-w-[200px]', className)}>
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
          {selectedEntity ? selectedEntity.entityId : placeholder}
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
                  onClick={() => handleSelect(entity.entityId)}
                  className={cn(
                    'flex w-full flex-col items-start px-3 py-1.5 text-left text-sm',
                    'hover:bg-accent hover:text-accent-foreground',
                    entity.entityId === value && 'bg-accent'
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
  )
}
