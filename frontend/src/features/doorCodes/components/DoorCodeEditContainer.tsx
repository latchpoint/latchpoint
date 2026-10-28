import { useMemo, useState } from 'react'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { DoorCodeEditPanel } from '@/features/doorCodes/components/DoorCodeEditPanel'
import { toDatetimeLocalValue, toUtcIsoFromDatetimeLocal } from '@/features/codes/utils/datetimeLocal'
import { daysMaskToSet, daysSetToMask } from '@/features/codes/utils/daysOfWeek'
import { parseOptionalTimeWindow, validateDigitsPin } from '@/features/codes/utils/validation'
import { parseOptionalMaxUses } from '@/features/doorCodes/utils/maxUses'

type Props = {
  code: DoorCode
  locks: Entity[]
  locksIsLoading: boolean
  locksError: unknown
  isSaving: boolean
  isDeleting: boolean
  onClose: () => void
  onUpdate: (id: number, req: UpdateDoorCodeRequest) => Promise<unknown>
  onDelete: (id: number, reauthPassword: string) => Promise<unknown>
}

function normalizeEntityId(value: string): string {
  return value.trim()
}

function parseManualLockIds(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,]+/g)
        .map((item) => normalizeEntityId(item))
        .filter(Boolean)
    )
  )
}

function sameSet<T>(a: Set<T>, b: Set<T>): boolean {
  return a.size === b.size && [...a].every((item) => b.has(item))
}

function sameDays(a: Set<number>, b: Set<number>): boolean {
  return daysSetToMask(a) === daysSetToMask(b)
}

/**
 * A form field seeded from the server. It follows the server until the user
 * edits it, then keeps their value. If the server value changes under an edit
 * the field is flagged as a conflict instead of being overwritten.
 */
function useServerField<T>(serverValue: T, isEqual: (a: T, b: T) => boolean = Object.is) {
  const [value, setValue] = useState<T>(serverValue)
  // The server value the field last took. The field is edited while value
  // differs from it.
  const [synced, setSynced] = useState<T>(serverValue)
  const [conflict, setConflict] = useState(false)

  if (!isEqual(serverValue, synced)) {
    setSynced(serverValue)
    if (isEqual(value, synced) || isEqual(value, serverValue)) {
      setValue(serverValue)
      setConflict(false)
    } else {
      setConflict(true)
    }
  }
  // Editing back to what the server has resolves the conflict.
  const isEdited = !isEqual(value, synced)
  if (conflict && !isEdited) setConflict(false)

  const reset = () => {
    setValue(synced)
    setConflict(false)
  }

  return { value, setValue, hasConflict: conflict && isEdited, reset }
}

export function DoorCodeEditContainer({ code, locks, locksIsLoading, locksError, isSaving, isDeleting, onClose, onUpdate, onDelete }: Props) {
  // The code refetches whenever it changes on the server (a scheduler retry, a
  // Retry or refused delete from another tab, a lock sync). Only the fields the
  // user hasn't edited take the new values.
  const label = useServerField(code.label || '')
  const isActive = useServerField(code.isActive)
  const startAtLocal = useServerField(toDatetimeLocalValue(code.startAt))
  const endAtLocal = useServerField(toDatetimeLocalValue(code.endAt))
  const days = useServerField(daysMaskToSet(code.daysOfWeek ?? 127), sameDays)
  const windowStart = useServerField(code.windowStart || '')
  const windowEnd = useServerField(code.windowEnd || '')
  const maxUses = useServerField(code.maxUses == null ? '' : String(code.maxUses))
  const selectedLocks = useServerField(new Set(code.lockEntityIds || []), sameSet)
  const serverFields = [label, isActive, startAtLocal, endAtLocal, days, windowStart, windowEnd, maxUses, selectedLocks]
  const hasServerConflict = serverFields.some((field) => field.hasConflict)

  const { value: editLabel, setValue: setEditLabel } = label
  const { value: editIsActive, setValue: setEditIsActive } = isActive
  const { value: editStartAtLocal, setValue: setEditStartAtLocal } = startAtLocal
  const { value: editEndAtLocal, setValue: setEditEndAtLocal } = endAtLocal
  const { value: editDays, setValue: setEditDays } = days
  const { value: editWindowStart, setValue: setEditWindowStart } = windowStart
  const { value: editWindowEnd, setValue: setEditWindowEnd } = windowEnd
  const { value: editMaxUses, setValue: setEditMaxUses } = maxUses
  const { value: editSelectedLocks, setValue: setEditSelectedLocks } = selectedLocks

  // Not from the server, so a refetch leaves them alone.
  const [editNewCode, setEditNewCode] = useState<string>('')
  const [editManualLockIds, setEditManualLockIds] = useState<string>('')
  const [editLockSearch, setEditLockSearch] = useState<string>('')
  const [editReauthPassword, setEditReauthPassword] = useState<string>('')
  // A refused delete refetches the code (it's now off), and its error has to
  // outlive that. It's cleared on the next submit.
  const [editError, setEditError] = useState<string | null>(null)

  // Puts the form back to what the server has. The password stays so the user
  // can still save or delete.
  const discardChanges = () => {
    serverFields.forEach((field) => field.reset())
    setEditNewCode('')
    setEditManualLockIds('')
  }

  const resolvedLockEntityIds = useMemo(() => {
    const locksFromPicker = Array.from(editSelectedLocks)
    if (locksFromPicker.length) return locksFromPicker
    return parseManualLockIds(editManualLockIds)
  }, [editManualLockIds, editSelectedLocks])

  const submitEdit = async () => {
    setEditError(null)
    const codeErr = editNewCode.trim() ? validateDigitsPin(editNewCode, { label: 'New code', required: false }) : null
    if (codeErr) {
      setEditError(codeErr)
      return
    }
    if (!editReauthPassword.trim()) {
      setEditError('Password is required for re-authentication.')
      return
    }

    const isSynced = code.source === 'synced'
    if (isSynced) {
      const req: UpdateDoorCodeRequest = {
        label: editLabel.trim(),
        reauthPassword: editReauthPassword,
      }
      try {
        await onUpdate(code.id, req)
        onClose()
      } catch (err) {
        setEditError(getErrorMessage(err) || 'Failed to update door code')
      }
      return
    }

    if (!resolvedLockEntityIds.length) {
      setEditError('Select at least one lock.')
      return
    }

    const startAt = toUtcIsoFromDatetimeLocal(editStartAtLocal)
    const endAt = toUtcIsoFromDatetimeLocal(editEndAtLocal)
    if (startAt && endAt && startAt > endAt) {
      setEditError('Active until must be after active from.')
      return
    }
    const isTemporary = code.codeType === 'temporary'
    const daysOfWeek = isTemporary ? daysSetToMask(editDays) : null
    if (isTemporary && daysOfWeek === 0) {
      setEditError('Select at least one day.')
      return
    }
    const { windowStart, windowEnd, error: windowError } = isTemporary
      ? parseOptionalTimeWindow(editWindowStart, editWindowEnd)
      : { windowStart: null, windowEnd: null, error: null }
    if (isTemporary && windowError) {
      setEditError(windowError)
      return
    }
    const { value: maxUses, error: maxUsesError } = parseOptionalMaxUses(editMaxUses)
    if (maxUsesError) {
      setEditError(maxUsesError)
      return
    }

    const req: UpdateDoorCodeRequest = {
      label: editLabel.trim(),
      isActive: editIsActive,
      maxUses,
      lockEntityIds: resolvedLockEntityIds,
      reauthPassword: editReauthPassword,
    }

    if (editNewCode.trim()) req.code = editNewCode.trim()
    if (isTemporary) {
      req.startAt = startAt
      req.endAt = endAt
      req.daysOfWeek = daysOfWeek
      req.windowStart = windowStart
      req.windowEnd = windowEnd
    }

    try {
      await onUpdate(code.id, req)
      onClose()
    } catch (err) {
      setEditError(getErrorMessage(err) || 'Failed to update door code')
    }
  }

  const submitDelete = async () => {
    setEditError(null)
    if (!editReauthPassword.trim()) {
      setEditError('Password is required for re-authentication.')
      return
    }
    const confirmMsg =
      code.source === 'synced'
        ? 'Delete this door code? This will also clear the code from the physical lock. This cannot be undone.'
        : 'Delete this door code? This cannot be undone.'
    const ok = window.confirm(confirmMsg)
    if (!ok) return
    try {
      await onDelete(code.id, editReauthPassword)
      onClose()
    } catch (err) {
      setEditError(getErrorMessage(err) || 'Failed to delete door code')
    }
  }

  return (
    <DoorCodeEditPanel
      code={code}
      editLabel={editLabel}
      onEditLabelChange={setEditLabel}
      editNewCode={editNewCode}
      onEditNewCodeChange={setEditNewCode}
      editMaxUses={editMaxUses}
      onEditMaxUsesChange={setEditMaxUses}
      editIsActive={editIsActive}
      onEditIsActiveChange={setEditIsActive}
      editStartAtLocal={editStartAtLocal}
      editEndAtLocal={editEndAtLocal}
      onActiveWindowChange={(next) => {
        setEditStartAtLocal(next.start)
        setEditEndAtLocal(next.end)
      }}
      editDays={editDays}
      onEditDaysChange={setEditDays}
      editWindowStart={editWindowStart}
      editWindowEnd={editWindowEnd}
      onEditWindowStartChange={setEditWindowStart}
      onEditWindowEndChange={setEditWindowEnd}
      lockPicker={{
        locks,
        isLoading: locksIsLoading,
        isError: Boolean(locksError),
        errorMessage: (
          <>
            Could not load entities: {getErrorMessage(locksError) || 'Unknown error'}. Enter lock entity ids manually below.
          </>
        ),
        search: editLockSearch,
        onSearchChange: setEditLockSearch,
        selected: editSelectedLocks,
        onSelectedChange: setEditSelectedLocks,
        manualValue: editManualLockIds,
        onManualValueChange: setEditManualLockIds,
        selectedCount: resolvedLockEntityIds.length,
      }}
      editReauthPassword={editReauthPassword}
      onEditReauthPasswordChange={setEditReauthPassword}
      editError={editError}
      hasServerConflict={hasServerConflict}
      onDiscardChanges={discardChanges}
      onCancel={onClose}
      onSave={submitEdit}
      onDelete={() => void submitDelete()}
      isSaving={isSaving}
      isDeleting={isDeleting}
    />
  )
}

