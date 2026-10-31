import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ReauthPasswordField } from '@/features/codes/components/ReauthPasswordField'
import { DoorCodeActiveToggle } from '@/features/doorCodes/components/DoorCodeActiveToggle'
import { DoorCodeEditActions } from '@/features/doorCodes/components/DoorCodeEditActions'
import { DoorCodeEditBasicsFields } from '@/features/doorCodes/components/DoorCodeEditBasicsFields'
import { DoorCodeLocksSection } from '@/features/doorCodes/components/DoorCodeLocksSection'
import { DoorCodeTemporaryRestrictionsFields } from '@/features/doorCodes/components/DoorCodeTemporaryRestrictionsFields'
import { isSyncedValidityEditable } from '@/features/doorCodes/utils/syncedValidity'
import type { DoorCode, Entity } from '@/types'

function SyncedFieldsWarning({ validityEditable }: { validityEditable: boolean }) {
  return (
    <Alert variant="warning" layout="inline">
      <AlertDescription>
        {validityEditable
          ? "This code is synced from the lock and has an end date. Its active window can be changed (but not cleared) and it can be turned on or off, which puts it on or takes it off its locks. The PIN, schedule, max uses, and lock assignments are controlled by the lock and will be overwritten on the next sync."
          : 'This code is synced from the lock. The PIN, active status, schedule, max uses, and lock assignments are controlled by the lock and will be overwritten on the next sync. Only the label can be edited here.'}
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
  /** Whether the code would be expired with the active window end being saved. */
  isExpired?: boolean

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
  /** Names the edited fields the server changed, ie "Label changed on the server.", or null. */
  serverConflictMessage: string | null
  onDiscardChanges: () => void
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
  isExpired = false,
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
  serverConflictMessage,
  onDiscardChanges,
  onCancel,
  onSave,
  onDelete,
  isSaving,
  isDeleting,
}: Props) {
  const isBusy = isSaving || isDeleting
  const isSynced = code.source === 'synced'
  // A synced code with an end date, eg retired at its end, can change its
  // active window and be turned on or off (#145, #189). The rest stays the lock's.
  const syncedValidityEditable = isSyncedValidityEditable(code)
  const activeLocked = isSynced && !syncedValidityEditable
  // The backend won't turn on an expired code, and moving its end later doesn't
  // turn it back on by itself (#145). A code that's still on can be turned off
  // and back again, since that only undoes the edit.
  const blockTurningOn = isExpired && !code.isActive && !editIsActive
  const isTemporary = code.codeType === 'temporary'
  // A one-time code's dates come from the API, and once it's past its end only
  // a later end turns it back on, so the window is on the form for it too (#184).
  const hasActiveWindow = isTemporary || code.codeType === 'one_time'

  return (
    <div className="mt-4 space-y-4 border-t border-input pt-4">
      {isSynced && <SyncedFieldsWarning validityEditable={syncedValidityEditable} />}

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

      {(hasActiveWindow || syncedValidityEditable) && (
        <DoorCodeTemporaryRestrictionsFields
          disabled={isBusy || isSynced}
          activeWindowDisabled={isBusy || activeLocked}
          showSchedule={isTemporary}
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
        disabled={isBusy || isSynced}
      />

      <DoorCodeActiveToggle
        id={`door-code-active-label-${code.id}`}
        checked={editIsActive}
        onCheckedChange={activeLocked ? undefined : onEditIsActiveChange}
        disabled={isBusy || activeLocked || blockTurningOn}
        hint={activeLocked ? 'Controlled by lock sync' : blockTurningOn ? 'Expired, set a later end for the active window to turn it on' : undefined}
      />

      <ReauthPasswordField
        id={`door-code-edit-password-${code.id}`}
        value={editReauthPassword}
        onChange={onEditReauthPasswordChange}
        disabled={isBusy}
        helpTip="Required to save changes or delete this code."
      />

      {/* Always rendered so screen readers announce the notice when it fills in.
          sr-only keeps the empty region out of the layout. */}
      <div role="status" className={serverConflictMessage ? undefined : 'sr-only'}>
        {serverConflictMessage ? (
          <Alert variant="warning" layout="inline" role="none">
            <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
              <span>{serverConflictMessage} Your unsaved changes are kept.</span>
              <Button type="button" variant="outline" size="sm" onClick={onDiscardChanges} disabled={isBusy}>
                Discard changes and reload
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}
      </div>

      {editError && (
        <Alert variant="error" layout="inline">
          <AlertDescription>{editError}</AlertDescription>
        </Alert>
      )}

      <DoorCodeEditActions isBusy={isBusy} isSaving={isSaving} isDeleting={isDeleting} onCancel={onCancel} onSave={onSave} onDelete={onDelete} />
    </div>
  )
}
