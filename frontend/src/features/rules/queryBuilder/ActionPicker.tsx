/**
 * Searchable dropdown for picking a single Home Assistant action
 * ("domain.service", e.g. "light.turn_on") for the THEN call-service action.
 *
 * Falls back to a plain text input when the services catalog is unavailable
 * (HA unreachable / empty catalog), and always allows committing free text via
 * the "Use ..." row so unknown or custom services stay expressible (ADR-0101).
 */
import { useId, useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { HomeAssistantServiceDefinition } from '@/services/homeAssistant'

interface ActionPickerProps {
  value: string
  onChange: (action: string) => void
  services: HomeAssistantServiceDefinition[]
  disabled?: boolean
  placeholder?: string
  className?: string
}

export function ActionPicker({
  value,
  onChange,
  services,
  disabled,
  placeholder = 'Select action...',
  className,
}: ActionPickerProps) {
  const [searchText, setSearchText] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const listboxId = useId()

  const options = useMemo(
    () =>
      services.map((svc) => ({
        id: `${svc.domain}.${svc.service}`,
        name: svc.name,
      })),
    [services]
  )

  const filteredOptions = useMemo(() => {
    if (!searchText.trim()) return options.slice(0, 50)
    const search = searchText.toLowerCase()
    return options
      .filter((o) => o.id.toLowerCase().includes(search) || o.name.toLowerCase().includes(search))
      .slice(0, 50)
  }, [options, searchText])

  const trimmedSearch = searchText.trim()
  const showFreeTextRow =
    trimmedSearch.length > 0 && !options.some((o) => o.id === trimmedSearch)

  const handleSelect = (actionId: string) => {
    onChange(actionId)
    setIsOpen(false)
    setSearchText('')
  }

  // No catalog (HA unreachable or empty): plain free-text input.
  if (options.length === 0) {
    return (
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="e.g., light.turn_on"
        disabled={disabled}
        className={className}
      />
    )
  }

  return (
    <div className={cn('relative min-w-[200px]', className)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
        className={cn(
          'flex h-8 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm',
          'hover:bg-accent hover:text-accent-foreground',
          disabled && 'cursor-not-allowed opacity-50'
        )}
      >
        <span className={cn('truncate', !value && 'text-muted-foreground')}>
          {value || placeholder}
        </span>
        <svg
          className="h-4 w-4 opacity-50"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && !disabled && (
        <div
          id={listboxId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full min-w-[300px] overflow-hidden rounded-md border bg-popover shadow-md"
        >
          <div className="p-2">
            <Input
              type="text"
              placeholder="Search actions..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="h-8"
              autoFocus
            />
          </div>
          <div className="max-h-48 overflow-y-auto">
            {filteredOptions.length === 0 && !showFreeTextRow ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">No actions found</div>
            ) : (
              <>
                {filteredOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    role="option"
                    aria-selected={option.id === value}
                    onClick={() => handleSelect(option.id)}
                    className={cn(
                      'flex w-full flex-col items-start px-3 py-1.5 text-left text-sm',
                      'hover:bg-accent hover:text-accent-foreground',
                      option.id === value && 'bg-accent'
                    )}
                  >
                    <span className="font-mono text-xs">{option.id}</span>
                    {option.name && option.name !== option.id && (
                      <span className="text-xs text-muted-foreground">{option.name}</span>
                    )}
                  </button>
                ))}
                {showFreeTextRow && (
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    onClick={() => handleSelect(trimmedSearch)}
                    className="flex w-full items-center px-3 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                  >
                    <span className="text-xs text-muted-foreground">
                      Use &ldquo;<span className="font-mono">{trimmedSearch}</span>&rdquo;
                    </span>
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
