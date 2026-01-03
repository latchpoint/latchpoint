import type { ReactNode } from 'react'

import { SectionCard } from '@/components/ui/section-card'
import { DoorCodeCreateActions } from '@/features/doorCodes/components/DoorCodeCreateActions'
import { DoorCodeCreateBasicsFields } from '@/features/doorCodes/components/DoorCodeCreateBasicsFields'
import { DoorCodeLocksField } from '@/features/doorCodes/components/DoorCodeLocksField'
import { DoorCodeTemporaryRestrictionsFields } from '@/features/doorCodes/components/DoorCodeTemporaryRestrictionsFields'
import type { Entity } from '@/types'

export type DoorCodeTypeOption = 'permanent' | 'temporary'

type SyncAction = {
  label: string
  pendingLabel?: string
  onClick: () => void
  isPending?: boolean
}

type Props = {
  codeType: DoorCodeTypeOption
  onCodeTypeChange: (next: DoorCodeTypeOption) => void
  label: string
  onLabelChange: (next: string) => void
  code: string
  onCodeChange: (next: string) => void
  maxUses: string
  onMaxUsesChange: (next: string) => void

  startAtLocal: string
  endAtLocal: string
  onActiveWindowChange: (next: { start: string; end: string }) => void

  days: Set<number>
  onDaysChange: (next: Set<number>) => void

  windowStart: string
  windowEnd: string
  onWindowStartChange: (next: string) => void
  onWindowEndChange: (next: string) => void

  lockPicker: {
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
  }

  reauthPassword: string
  onReauthPasswordChange: (next: string) => void

  error: string | null
  onSubmit: () => void

  isBusy: boolean
}

export function DoorCodeCreateForm({
  codeType,
  onCodeTypeChange,
  label,
  onLabelChange,
  code,
  onCodeChange,
  maxUses,
  onMaxUsesChange,
  startAtLocal,
  endAtLocal,
  onActiveWindowChange,
  days,
  onDaysChange,
  windowStart,
  windowEnd,
  onWindowStartChange,
  onWindowEndChange,
  lockPicker,
  reauthPassword,
  onReauthPasswordChange,
  error,
  onSubmit,
  isBusy,
}: Props) {
  return (
    <SectionCard title="Create Door Code" contentClassName="space-y-4">
      <DoorCodeCreateBasicsFields
        codeType={codeType}
        onCodeTypeChange={onCodeTypeChange}
        label={label}
        onLabelChange={onLabelChange}
        code={code}
        onCodeChange={onCodeChange}
        maxUses={maxUses}
        onMaxUsesChange={onMaxUsesChange}
        isBusy={isBusy}
      />

      {codeType === 'temporary' && (
        <DoorCodeTemporaryRestrictionsFields
          disabled={isBusy}
          activeWindow={{ start: startAtLocal, end: endAtLocal }}
          onActiveWindowChange={onActiveWindowChange}
          days={days}
          onDaysChange={onDaysChange}
          timeWindow={{ start: windowStart, end: windowEnd }}
          onTimeWindowStartChange={onWindowStartChange}
          onTimeWindowEndChange={onWindowEndChange}
          startId="door-code-create-window-start"
          endId="door-code-create-window-end"
        />
      )}

      <DoorCodeLocksField
        locks={lockPicker.locks}
        isLoading={lockPicker.isLoading}
        isError={lockPicker.isError}
        errorMessage={lockPicker.errorMessage}
        search={lockPicker.search}
        onSearchChange={lockPicker.onSearchChange}
        selected={lockPicker.selected}
        onSelectedChange={lockPicker.onSelectedChange}
        manualValue={lockPicker.manualValue}
        onManualValueChange={lockPicker.onManualValueChange}
        selectedCount={lockPicker.selectedCount}
        emptyWarning={lockPicker.emptyWarning}
        emptyActions={lockPicker.emptyActions}
        disabled={isBusy}
      />

      <DoorCodeCreateActions
        reauthPassword={reauthPassword}
        onReauthPasswordChange={onReauthPasswordChange}
        error={error}
        onSubmit={onSubmit}
        isBusy={isBusy}
      />
    </SectionCard>
  )
}
