import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { ReauthPasswordField } from '@/features/codes/components/ReauthPasswordField'
import { DoorCodeActiveToggle } from '@/features/doorCodes/components/DoorCodeActiveToggle'
import { DoorCodeEditActions } from '@/features/doorCodes/components/DoorCodeEditActions'
import { DoorCodeEditBasicsFields } from '@/features/doorCodes/components/DoorCodeEditBasicsFields'
import { DoorCodeLocksSection } from '@/features/doorCodes/components/DoorCodeLocksSection'
import { DoorCodeTemporaryRestrictionsFields } from '@/features/doorCodes/components/DoorCodeTemporaryRestrictionsFields'
import type { DoorCode, Entity } from '@/types'

function SyncedFieldsWarning() {
  return (
    <Alert variant="warning" layout="inline">
      <AlertDescription>
        This code is synced from the lock. The PIN, active status, and schedule are controlled by the lock and will be
        overwritten on the next sync. Only the label, max uses, and lock assignments can be edited here.
      </AlertDescription>
    </Alert>
  )
}

type Props = {
  code: DoorCode
  editLabel: string
  onEditLabelChange: (next: string) => void
  editNewCode: string
  onEditNewCodeChange: (next: string) => void
  editMaxUses: string
  onEditMaxUsesChange: (next: string) => void
  editIsActive: boolean
  onEditIsActiveChange: (next: boolean) => void

  editStartAtLocal: string
  editEndAtLocal: string
  onActiveWindowChange: (next: { start: string; end: string }) => void

  editDays: Set<number>
  onEditDaysChange: (next: Set<number>) => void

  editWindowStart: string
  editWindowEnd: string
  onEditWindowStartChange: (next: string) => void
  onEditWindowEndChange: (next: string) => void

  lockPicker: {
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
  }

  editReauthPassword: string
  onEditReauthPasswordChange: (next: string) => void

  editError: string | null
  onCancel: () => void
  onSave: () => void
  onDelete: () => void

  isSaving: boolean
  isDeleting: boolean
}

export function DoorCodeEditPanel({
  code,
  editLabel,
  onEditLabelChange,
  editNewCode,
  onEditNewCodeChange,
  editMaxUses,
  onEditMaxUsesChange,
  editIsActive,
  onEditIsActiveChange,
  editStartAtLocal,
  editEndAtLocal,
  onActiveWindowChange,
  editDays,
  onEditDaysChange,
  editWindowStart,
  editWindowEnd,
  onEditWindowStartChange,
  onEditWindowEndChange,
  lockPicker,
  editReauthPassword,
  onEditReauthPasswordChange,
  editError,
  onCancel,
  onSave,
  onDelete,
  isSaving,
  isDeleting,
}: Props) {
  const isBusy = isSaving || isDeleting
  const isSynced = code.source === 'synced'
  const isTemporary = code.codeType === 'temporary'

  return (
    <div className="mt-4 space-y-4 border-t border-input pt-4">
      {isSynced && <SyncedFieldsWarning />}

      <DoorCodeEditBasicsFields
        codeId={code.id}
        label={editLabel}
        onLabelChange={onEditLabelChange}
        newCode={editNewCode}
        onNewCodeChange={onEditNewCodeChange}
        maxUses={editMaxUses}
        onMaxUsesChange={onEditMaxUsesChange}
        isBusy={isBusy}
        isSynced={isSynced}
      />

      {isTemporary && (
        <DoorCodeTemporaryRestrictionsFields
          disabled={isBusy}
          activeWindow={{ start: editStartAtLocal, end: editEndAtLocal }}
          onActiveWindowChange={onActiveWindowChange}
          days={editDays}
          onDaysChange={onEditDaysChange}
          timeWindow={{ start: editWindowStart, end: editWindowEnd }}
          onTimeWindowStartChange={onEditWindowStartChange}
          onTimeWindowEndChange={onEditWindowEndChange}
          startId={`door-code-edit-window-start-${code.id}`}
          endId={`door-code-edit-window-end-${code.id}`}
          showActiveWindowHelper={false}
          showTimeWindowHelp={false}
        />
      )}

      <DoorCodeLocksSection
        title={lockPicker.title}
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
        disabled={isBusy}
      />

      <DoorCodeActiveToggle id={`door-code-active-label-${code.id}`} checked={editIsActive} onCheckedChange={isSynced ? undefined : onEditIsActiveChange} disabled={isBusy || isSynced} hint={isSynced ? 'Controlled by lock sync' : undefined} />

      <ReauthPasswordField
        id={`door-code-edit-password-${code.id}`}
        value={editReauthPassword}
        onChange={onEditReauthPasswordChange}
        disabled={isBusy}
        helpTip="Required to save changes or delete this code."
      />

      {editError && (
        <Alert variant="error" layout="inline">
          <AlertDescription>{editError}</AlertDescription>
        </Alert>
      )}

      <DoorCodeEditActions isBusy={isBusy} isSaving={isSaving} isDeleting={isDeleting} onCancel={onCancel} onSave={onSave} onDelete={onDelete} />
    </div>
  )
}
