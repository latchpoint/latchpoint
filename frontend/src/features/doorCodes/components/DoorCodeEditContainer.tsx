import { useEffect, useMemo, useState } from 'react'
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

export function DoorCodeEditContainer({ code, locks, locksIsLoading, locksError, isSaving, isDeleting, onClose, onUpdate, onDelete }: Props) {
  const [editLabel, setEditLabel] = useState<string>('')
  const [editNewCode, setEditNewCode] = useState<string>('')
  const [editIsActive, setEditIsActive] = useState<boolean>(true)
  const [editStartAtLocal, setEditStartAtLocal] = useState<string>('')
  const [editEndAtLocal, setEditEndAtLocal] = useState<string>('')
  const [editDays, setEditDays] = useState<Set<number>>(() => daysMaskToSet(127))
  const [editWindowStart, setEditWindowStart] = useState<string>('')
  const [editWindowEnd, setEditWindowEnd] = useState<string>('')
  const [editMaxUses, setEditMaxUses] = useState<string>('')
  const [editSelectedLocks, setEditSelectedLocks] = useState<Set<string>>(() => new Set())
  const [editManualLockIds, setEditManualLockIds] = useState<string>('')
  const [editLockSearch, setEditLockSearch] = useState<string>('')
  const [editReauthPassword, setEditReauthPassword] = useState<string>('')
  const [editError, setEditError] = useState<string | null>(null)

  useEffect(() => {
    setEditLabel(code.label || '')
    setEditNewCode('')
    setEditIsActive(code.isActive)
    setEditStartAtLocal(toDatetimeLocalValue(code.startAt))
    setEditEndAtLocal(toDatetimeLocalValue(code.endAt))
    setEditDays(daysMaskToSet(code.daysOfWeek ?? 127))
    setEditWindowStart(code.windowStart || '')
    setEditWindowEnd(code.windowEnd || '')
    setEditMaxUses(code.maxUses == null ? '' : String(code.maxUses))
    setEditSelectedLocks(new Set(code.lockEntityIds || []))
    setEditManualLockIds('')
    setEditLockSearch('')
    setEditReauthPassword('')
    setEditError(null)
  }, [code])

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
    const ok = window.confirm('Delete this door code? This cannot be undone.')
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
      onCancel={onClose}
      onSave={submitEdit}
      onDelete={() => void submitDelete()}
      isSaving={isSaving}
      isDeleting={isDeleting}
    />
  )
}

