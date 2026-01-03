import type { ReactNode } from 'react'

import type { Entity } from '@/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'

type SyncAction = {
  label: string
  pendingLabel?: string
  onClick: () => void
  isPending?: boolean
}

type Props = {
  locks: Entity[]
  isLoading: boolean
  isError: boolean
  errorMessage?: ReactNode

  search: string
  onSearchChange: (next: string) => void

  selected: Set<string>
  onSelectedChange: (next: Set<string>) => void

  manualValue: string
  onManualValueChange: (next: string) => void

  selectedCountLabel?: ReactNode
  selectedCount?: number

  emptyWarning?: ReactNode
  emptyActions?: SyncAction[]

  disabled?: boolean
  manualPlaceholder?: string
}

export function LockEntityPicker({
  locks,
  isLoading,
  isError,
  errorMessage,
  search,
  onSearchChange,
  selected,
  onSelectedChange,
  manualValue,
  onManualValueChange,
  selectedCount,
  selectedCountLabel = 'Selected',
  emptyWarning,
  emptyActions,
  disabled,
  manualPlaceholder = 'e.g. lock.front_door, lock.back_door',
}: Props) {
  const canPick = !isError && locks.length > 0

  const filteredLocks = (() => {
    const query = search.trim().toLowerCase()
    if (!query) return locks
    return locks.filter((lock) => {
      const haystack = `${lock.name} ${lock.entityId}`.toLowerCase()
      return haystack.includes(query)
    })
  })()

  if (isLoading) return <LoadingInline label="Loading locks…" />

  if (!canPick) {
    return (
      <div className="space-y-2">
        {isError && errorMessage && (
          <Alert variant="error" layout="inline">
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        )}

        {!isError && locks.length === 0 && emptyWarning && (
          <Alert variant="warning" layout="inline">
            <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
              <span>{emptyWarning}</span>
              {emptyActions && emptyActions.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {emptyActions.map((action) => (
                    <Button
                      key={action.label}
                      variant="secondary"
                      onClick={action.onClick}
                      disabled={action.isPending || disabled}
                    >
                      {action.isPending ? action.pendingLabel || 'Syncing…' : action.label}
                    </Button>
                  ))}
                </div>
              )}
            </AlertDescription>
          </Alert>
        )}

        <Input
          value={manualValue}
          onChange={(e) => onManualValueChange(e.target.value)}
          placeholder={manualPlaceholder}
          disabled={disabled}
        />
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <Input
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        placeholder="Search locks…"
        disabled={disabled}
      />
      <div className="max-h-56 overflow-auto rounded-md border border-input p-3">
        <div className="space-y-2">
          {filteredLocks.map((lock) => (
            <label key={lock.entityId} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={selected.has(lock.entityId)}
                onChange={(e) => {
                  const next = new Set(selected)
                  if (e.target.checked) next.add(lock.entityId)
                  else next.delete(lock.entityId)
                  onSelectedChange(next)
                }}
                disabled={disabled}
              />
              <span className="truncate">
                {lock.name} <span className="text-muted-foreground">({lock.entityId})</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      {typeof selectedCount === 'number' && (
        <div className="text-xs text-muted-foreground">
          {selectedCountLabel}: {selectedCount}
        </div>
      )}
    </div>
  )
}

