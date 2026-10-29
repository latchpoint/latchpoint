import { useMemo, useState } from 'react'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { DoorCodeEditPanel } from '@/features/doorCodes/components/DoorCodeEditPanel'
import { toDatetimeLocalValue, toUtcIsoFromDatetimeLocal } from '@/features/codes/utils/datetimeLocal'
import { daysMaskToSet, daysSetToMask } from '@/features/codes/utils/daysOfWeek'
import { parseOptionalTimeWindow, validateDigitsPin } from '@/features/codes/utils/validation'
import { parseOptionalMaxUses } from '@/features/doorCodes/utils/maxUses'
import { isSyncedValidityEditable } from '@/features/doorCodes/utils/syncedValidity'

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

type Range = { start: string; end: string }

function sameSet<T>(a: Set<T>, b: Set<T>): boolean {
  return a.size === b.size && [...a].every((item) => b.has(item))
}

function copySet<T>(set: Set<T>): Set<T> {
  return new Set(set)
}

function sameDays(a: Set<number>, b: Set<number>): boolean {
  return daysSetToMask(a) === daysSetToMask(b)
}

function sameRange(a: Range, b: Range): boolean {
  return a.start === b.start && a.end === b.end
}

// Keeps what the user added and removed relative to base, on top of the
// server's set. Both sides only ever agree on a member they both touched (it
// was either in base or it wasn't), so this never conflicts.
function mergeSet<T>(base: Set<T>, mine: Set<T>, theirs: Set<T>): Set<T> {
  const merged = new Set(theirs)
  for (const item of mine) if (!base.has(item)) merged.add(item)
  for (const item of base) if (!mine.has(item)) merged.delete(item)
  return merged
}

// mergeSet for the days of week, as masks.
function mergeDays(base: Set<number>, mine: Set<number>, theirs: Set<number>): Set<number> {
  const baseMask = daysSetToMask(base)
  const mineMask = daysSetToMask(mine)
  const added = mineMask & ~baseMask
  const removed = baseMask & ~mineMask
  return daysMaskToSet((daysSetToMask(theirs) & ~removed) | added)
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

type ServerFieldOptions<T> = {
  isEqual?: (a: T, b: T) => boolean
  /** Combines the user's edit with a new server value. Without one the edit is kept whole and flagged. */
  merge?: (base: T, mine: T, theirs: T) => T
  /** Copies a value so the form never shares an object with the synced value. */
  copy?: (value: T) => T
}

/**
 * A form field seeded from the server. It follows the server until the user
 * edits it. After that a new server value is merged into the edit if the field
 * has a merge, or else the edit is kept and the field is flagged as a conflict.
 */
function useServerField<T>(serverValue: T, options: ServerFieldOptions<T> = {}) {
  const { isEqual = Object.is, merge, copy = (value: T) => value } = options
  const [value, setValue] = useState<T>(() => copy(serverValue))
  // The server value the field last took. The field is edited while value
  // differs from it.
  const [synced, setSynced] = useState<T>(serverValue)
  const [conflict, setConflict] = useState(false)

  if (!isEqual(serverValue, synced)) {
    setSynced(serverValue)
    if (isEqual(value, synced) || isEqual(value, serverValue)) {
      setValue(copy(serverValue))
      setConflict(false)
    } else if (merge) {
      setValue(merge(synced, value, serverValue))
    } else {
      setConflict(true)
    }
  }
  // Editing back to what the server has resolves the conflict.
  const isEdited = !isEqual(value, synced)
  if (conflict && !isEdited) setConflict(false)

  const reset = () => {
    setValue(copy(synced))
    setConflict(false)
  }

  return { value, setValue, isEdited, hasConflict: conflict && isEdited, reset }
}

export function DoorCodeEditContainer({ code, locks, locksIsLoading, locksError, isSaving, isDeleting, onClose, onUpdate, onDelete }: Props) {
  // The code refetches whenever it changes on the server (a scheduler retry, a
  // Retry or refused delete from another tab, a lock sync). Only the fields the
  // user hasn't edited take the new values, and a save sends only the edited ones.
  const labelField = useServerField(code.label || '')
  const isActiveField = useServerField(code.isActive)
  // The date range and the time window are each one field, so an edit to one
  // end and a server change to the other don't blend into a range nobody chose.
  const dateRangeField = useServerField<Range>(
    { start: toDatetimeLocalValue(code.startAt), end: toDatetimeLocalValue(code.endAt) },
    { isEqual: sameRange },
  )
  const daysField = useServerField(daysMaskToSet(code.daysOfWeek ?? 127), {
    isEqual: sameDays,
    merge: mergeDays,
    copy: copySet,
  })
  const timeWindowField = useServerField<Range>(
    { start: code.windowStart || '', end: code.windowEnd || '' },
    { isEqual: sameRange },
  )
  const maxUsesField = useServerField(code.maxUses == null ? '' : String(code.maxUses))
  // A lock whose removal is still waiting on its slot clear stays in
  // lockEntityIds until the clear works, but the user already took it off. It
  // starts unticked so a save only keeps it when the user ticks it again, which
  // is what cancels the removal on the backend (#151).
  const serverLockIds = useMemo(() => {
    const removing = new Set(
      (code.lockSlotAssignments || []).filter((a) => a.pendingRemoval).map((a) => a.lockEntityId),
    )
    return (code.lockEntityIds || []).filter((id) => !removing.has(id))
  }, [code.lockEntityIds, code.lockSlotAssignments])
  const locksField = useServerField(new Set(serverLockIds), {
    isEqual: sameSet,
    merge: mergeSet,
    copy: copySet,
  })
  const serverFields = [
    { field: labelField, name: 'Label' },
    { field: isActiveField, name: 'Active' },
    { field: dateRangeField, name: 'Active date range' },
    { field: daysField, name: 'Days of week' },
    { field: timeWindowField, name: 'Time window' },
    { field: maxUsesField, name: 'Max uses' },
    { field: locksField, name: 'Locks' },
  ]

  const { value: editLabel, setValue: setEditLabel } = labelField
  const { value: editIsActive, setValue: setEditIsActive } = isActiveField
  const { value: editDateRange, setValue: setEditDateRange } = dateRangeField
  const { value: editDays, setValue: setEditDays } = daysField
  const { value: editTimeWindow, setValue: setEditTimeWindow } = timeWindowField
  const { value: editMaxUses, setValue: setEditMaxUses } = maxUsesField
  const { value: editSelectedLocks, setValue: setEditSelectedLocks } = locksField

  // Not from the server, so a refetch leaves them alone.
  const [editNewCode, setEditNewCode] = useState<string>('')
  const [editManualLockIds, setEditManualLockIds] = useState<string>('')
  const [editLockSearch, setEditLockSearch] = useState<string>('')
  const [editReauthPassword, setEditReauthPassword] = useState<string>('')
  // A refused delete refetches the code (it's now off), and its error has to
  // outlive that. It's cleared on the next submit.
  const [editError, setEditError] = useState<string | null>(null)

  // A typed new PIN would replace a PIN that changed on the server, so flag it.
  const typedPin = editNewCode.trim()
  const serverPinKey = `${code.pin ?? ''}|${code.pinLength}`
  const [syncedPinKey, setSyncedPinKey] = useState(serverPinKey)
  const [pinConflict, setPinConflict] = useState(false)
  if (serverPinKey !== syncedPinKey) {
    setSyncedPinKey(serverPinKey)
    if (typedPin && typedPin !== code.pin) setPinConflict(true)
  }
  // Like the other fields, clearing the PIN or typing the server's resolves it.
  if (pinConflict && (!typedPin || typedPin === code.pin)) setPinConflict(false)
  const hasPinConflict = pinConflict && typedPin !== '' && typedPin !== code.pin

  const conflictedFieldNames = serverFields.filter(({ field }) => field.hasConflict).map(({ name }) => name)
  if (hasPinConflict) conflictedFieldNames.push('New code')
  const serverConflictMessage = conflictedFieldNames.length
    ? `${joinNames(conflictedFieldNames)} changed on the server.`
    : null

  // Puts the form back to what the server has. The password stays so the user
  // can still save or delete.
  const discardChanges = () => {
    serverFields.forEach(({ field }) => field.reset())
    setEditNewCode('')
    setPinConflict(false)
    setEditManualLockIds('')
  }

  // Expired with the end date the save would send. An untouched range goes by
  // the backend's validity, since the input drops the seconds. An edited one is
  // checked against when it was last edited, since render can't read the clock.
  const [rangeEditedAt, setRangeEditedAt] = useState(() => Date.now())
  const editedEndAt = toUtcIsoFromDatetimeLocal(editDateRange.end)
  const isExpired = dateRangeField.isEdited
    ? editedEndAt != null && new Date(editedEndAt).getTime() <= rangeEditedAt
    : code.validity === 'expired'

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

    // Only the fields the user edited go in the PATCH. Sending the rest would
    // write back whatever this tab last fetched, ie turn a code back on that was
    // turned off elsewhere.
    const req: UpdateDoorCodeRequest = { reauthPassword: editReauthPassword }
    if (labelField.isEdited) req.label = editLabel.trim()

    const isSynced = code.source === 'synced'
    if (isSynced) {
      // An off synced code with an end date can change its active window and
      // come back on (#145). Everything else on a synced code is the lock's.
      if (isSyncedValidityEditable(code)) {
        if (isActiveField.isEdited) req.isActive = editIsActive
        if (dateRangeField.isEdited) {
          const syncedStartAt = toUtcIsoFromDatetimeLocal(editDateRange.start)
          const syncedEndAt = toUtcIsoFromDatetimeLocal(editDateRange.end)
          if (syncedStartAt && syncedEndAt && syncedStartAt >= syncedEndAt) {
            setEditError('The active window must end after it starts.')
            return
          }
          req.startAt = syncedStartAt
          req.endAt = syncedEndAt
        }
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

    const startAt = toUtcIsoFromDatetimeLocal(editDateRange.start)
    const endAt = toUtcIsoFromDatetimeLocal(editDateRange.end)
    if (startAt && endAt && startAt >= endAt) {
      setEditError('The active window must end after it starts.')
      return
    }
    const isTemporary = code.codeType === 'temporary'
    const daysOfWeek = isTemporary ? daysSetToMask(editDays) : null
    if (isTemporary && daysOfWeek === 0) {
      setEditError('Select at least one day.')
      return
    }
    const { windowStart, windowEnd, error: windowError } = isTemporary
      ? parseOptionalTimeWindow(editTimeWindow.start, editTimeWindow.end)
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

    // Off is always sent. The backend uses it to clear a PIN an inactive code
    // may still have on a lock, which nothing else in the UI can trigger, and it
    // can never push the code. On still needs a real edit, so a stale tab can't
    // turn a code back on.
    if (isActiveField.isEdited || !editIsActive) req.isActive = editIsActive
    if (maxUsesField.isEdited) req.maxUses = maxUses
    // The manual ids stand in for the picker when it's empty, so compare what
    // would be saved with the server's locks (without the ones being removed).
    if (!sameSet(new Set(resolvedLockEntityIds), new Set(serverLockIds))) {
      req.lockEntityIds = resolvedLockEntityIds
    }
    if (typedPin) req.code = typedPin
    if (isTemporary) {
      if (dateRangeField.isEdited) {
        req.startAt = startAt
        req.endAt = endAt
      }
      if (daysField.isEdited) req.daysOfWeek = daysOfWeek
      if (timeWindowField.isEdited) {
        req.windowStart = windowStart
        req.windowEnd = windowEnd
      }
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
      isExpired={isExpired}
      editStartAtLocal={editDateRange.start}
      editEndAtLocal={editDateRange.end}
      onActiveWindowChange={(next) => {
        setRangeEditedAt(Date.now())
        setEditDateRange({ start: next.start, end: next.end })
      }}
      editDays={editDays}
      onEditDaysChange={setEditDays}
      editWindowStart={editTimeWindow.start}
      editWindowEnd={editTimeWindow.end}
      onEditWindowStartChange={(start) => setEditTimeWindow((prev) => ({ ...prev, start }))}
      onEditWindowEndChange={(end) => setEditTimeWindow((prev) => ({ ...prev, end }))}
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
      serverConflictMessage={serverConflictMessage}
      onDiscardChanges={discardChanges}
      onCancel={onClose}
      onSave={submitEdit}
      onDelete={() => void submitDelete()}
      isSaving={isSaving}
      isDeleting={isDeleting}
    />
  )
}

