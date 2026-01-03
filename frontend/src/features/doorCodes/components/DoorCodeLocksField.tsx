import type { ReactNode } from 'react'
import { FormField } from '@/components/ui/form-field'
import { DoorCodeLocksPicker } from '@/features/doorCodes/components/DoorCodeLocksPicker'
import type { Entity } from '@/types'

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
  selectedCount: number
  emptyWarning?: ReactNode
  emptyActions?: SyncAction[]
  disabled: boolean
}

export function DoorCodeLocksField(props: Props) {
  return (
    <FormField label="Locks" help="Select which locks this code applies to. This list comes from the synced entity registry (same as Rules).">
      <DoorCodeLocksPicker {...props} />
    </FormField>
  )
}

