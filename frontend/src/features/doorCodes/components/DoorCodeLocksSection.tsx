import type { ReactNode } from 'react'
import { HelpTip } from '@/components/ui/help-tip'
import { DoorCodeLocksPicker } from '@/features/doorCodes/components/DoorCodeLocksPicker'
import type { Entity } from '@/types'

type Props = {
  title?: ReactNode
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
  disabled: boolean
}

export function DoorCodeLocksSection({
  title,
  disabled,
  ...picker
}: Props) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">{title ?? 'Locks'}</div>
        <HelpTip content="Select which Home Assistant locks this code applies to." />
      </div>
      <DoorCodeLocksPicker {...picker} disabled={disabled} />
    </div>
  )
}

