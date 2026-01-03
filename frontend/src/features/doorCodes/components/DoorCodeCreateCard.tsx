import { useMemo, useState } from 'react'
import type { Entity, CreateDoorCodeRequest } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { DoorCodeCreateForm, type DoorCodeTypeOption } from '@/features/doorCodes/components/DoorCodeCreateForm'
import { toUtcIsoFromDatetimeLocal } from '@/features/codes/utils/datetimeLocal'
import { daysMaskToSet, daysSetToMask } from '@/features/codes/utils/daysOfWeek'
import { parseOptionalTimeWindow, validateDigitsPin } from '@/features/codes/utils/validation'
import { parseOptionalMaxUses } from '@/features/doorCodes/utils/maxUses'

type Props = {
  userId: string
  locks: Entity[]
  locksIsLoading: boolean
  locksError: unknown
  syncHa: { onClick: () => void; isPending: boolean }
  syncZwave: { onClick: () => void; isPending: boolean }
  isPending: boolean
  onCreate: (req: CreateDoorCodeRequest) => Promise<unknown>
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

export function DoorCodeCreateCard({ userId, locks, locksIsLoading, locksError, syncHa, syncZwave, isPending, onCreate }: Props) {
  const [createLabel, setCreateLabel] = useState<string>('')
  const [createCode, setCreateCode] = useState<string>('')
  const [createCodeType, setCreateCodeType] = useState<DoorCodeTypeOption>('permanent')
  const [createStartAtLocal, setCreateStartAtLocal] = useState<string>('')
  const [createEndAtLocal, setCreateEndAtLocal] = useState<string>('')
  const [createDays, setCreateDays] = useState<Set<number>>(() => daysMaskToSet(127))
  const [createWindowStart, setCreateWindowStart] = useState<string>('')
  const [createWindowEnd, setCreateWindowEnd] = useState<string>('')
  const [createMaxUses, setCreateMaxUses] = useState<string>('')
  const [createSelectedLocks, setCreateSelectedLocks] = useState<Set<string>>(() => new Set())
  const [createManualLockIds, setCreateManualLockIds] = useState<string>('')
  const [createLockSearch, setCreateLockSearch] = useState<string>('')
  const [createReauthPassword, setCreateReauthPassword] = useState<string>('')
  const [createError, setCreateError] = useState<string | null>(null)

  const resolvedLockEntityIds = useMemo(() => {
    const locksFromPicker = Array.from(createSelectedLocks)
    if (locksFromPicker.length) return locksFromPicker
    return parseManualLockIds(createManualLockIds)
  }, [createManualLockIds, createSelectedLocks])

  const submitCreate = async () => {
    setCreateError(null)
    if (!userId) {
      setCreateError('Select a user first.')
      return
    }
    const codeErr = validateDigitsPin(createCode, { label: 'Code', required: true })
    if (codeErr) {
      setCreateError(codeErr)
      return
    }
    if (!createReauthPassword.trim()) {
      setCreateError('Password is required for re-authentication.')
      return
    }

    if (!resolvedLockEntityIds.length) {
      setCreateError('Select at least one lock.')
      return
    }

    const isTemporary = createCodeType === 'temporary'
    const startAt = isTemporary ? toUtcIsoFromDatetimeLocal(createStartAtLocal) : null
    const endAt = isTemporary ? toUtcIsoFromDatetimeLocal(createEndAtLocal) : null
    if (isTemporary && startAt && endAt && startAt > endAt) {
      setCreateError('Active until must be after active from.')
      return
    }
    const daysOfWeek = isTemporary ? daysSetToMask(createDays) : null
    if (isTemporary && daysOfWeek === 0) {
      setCreateError('Select at least one day.')
      return
    }
    const { windowStart, windowEnd, error: windowError } = isTemporary
      ? parseOptionalTimeWindow(createWindowStart, createWindowEnd)
      : { windowStart: null, windowEnd: null, error: null }
    if (isTemporary && windowError) {
      setCreateError(windowError)
      return
    }
    const { value: maxUses, error: maxUsesError } = parseOptionalMaxUses(createMaxUses)
    if (maxUsesError) {
      setCreateError(maxUsesError)
      return
    }

    try {
      await onCreate({
        userId,
        label: createLabel.trim(),
        code: createCode.trim(),
        codeType: createCodeType,
        startAt,
        endAt,
        daysOfWeek,
        windowStart,
        windowEnd,
        maxUses,
        lockEntityIds: resolvedLockEntityIds,
        reauthPassword: createReauthPassword,
      })
      setCreateLabel('')
      setCreateCode('')
      setCreateCodeType('permanent')
      setCreateStartAtLocal('')
      setCreateEndAtLocal('')
      setCreateDays(daysMaskToSet(127))
      setCreateWindowStart('')
      setCreateWindowEnd('')
      setCreateMaxUses('')
      setCreateSelectedLocks(new Set())
      setCreateManualLockIds('')
      setCreateLockSearch('')
      setCreateReauthPassword('')
    } catch (err) {
      setCreateError(getErrorMessage(err) || 'Failed to create door code')
    }
  }

  return (
    <DoorCodeCreateForm
      codeType={createCodeType}
      onCodeTypeChange={setCreateCodeType}
      label={createLabel}
      onLabelChange={setCreateLabel}
      code={createCode}
      onCodeChange={setCreateCode}
      maxUses={createMaxUses}
      onMaxUsesChange={setCreateMaxUses}
      startAtLocal={createStartAtLocal}
      endAtLocal={createEndAtLocal}
      onActiveWindowChange={(next) => {
        setCreateStartAtLocal(next.start)
        setCreateEndAtLocal(next.end)
      }}
      days={createDays}
      onDaysChange={setCreateDays}
      windowStart={createWindowStart}
      windowEnd={createWindowEnd}
      onWindowStartChange={setCreateWindowStart}
      onWindowEndChange={setCreateWindowEnd}
      lockPicker={{
        locks,
        isLoading: locksIsLoading,
        isError: Boolean(locksError),
        errorMessage: (
          <>
            Could not load entities: {getErrorMessage(locksError) || 'Unknown error'}. Enter lock entity ids manually below.
          </>
        ),
        search: createLockSearch,
        onSearchChange: setCreateLockSearch,
        selected: createSelectedLocks,
        onSelectedChange: setCreateSelectedLocks,
        manualValue: createManualLockIds,
        onManualValueChange: setCreateManualLockIds,
        selectedCount: resolvedLockEntityIds.length,
        emptyWarning: 'No lock entities found in the registry.',
        emptyActions: [
          { label: 'Sync HA', pendingLabel: 'Syncing…', onClick: syncHa.onClick, isPending: syncHa.isPending },
          { label: 'Sync Z-Wave', pendingLabel: 'Syncing…', onClick: syncZwave.onClick, isPending: syncZwave.isPending },
        ],
      }}
      reauthPassword={createReauthPassword}
      onReauthPasswordChange={setCreateReauthPassword}
      error={createError}
      onSubmit={submitCreate}
      isBusy={isPending}
    />
  )
}

