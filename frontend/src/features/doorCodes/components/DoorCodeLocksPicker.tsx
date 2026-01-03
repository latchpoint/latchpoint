import type { ReactNode } from 'react'
import { LockEntityPicker } from '@/features/doorCodes/components/LockEntityPicker'
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

export function DoorCodeLocksPicker(props: Props) {
  return <LockEntityPicker {...props} />
}

