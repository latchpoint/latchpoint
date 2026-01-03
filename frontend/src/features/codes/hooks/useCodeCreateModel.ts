import { useState } from 'react'
import type { AlarmStateType } from '@/lib/constants'
import type { CreateCodeRequest } from '@/types'
import { getErrorMessage } from '@/types/errors'
import type { CreateCodeTypeOption } from '@/lib/typeGuards'
import { toUtcIsoFromDatetimeLocal } from '@/features/codes/utils/datetimeLocal'
import { daysMaskToSet, daysSetToMask } from '@/features/codes/utils/daysOfWeek'
import { parseOptionalTimeWindow, validateDigitsPin } from '@/features/codes/utils/validation'

const DEFAULT_DAYS_MASK = 127

export function useCodeCreateModel(opts: {
  userId: string
  armableStates: AlarmStateType[]
  onCreate: (req: CreateCodeRequest) => Promise<unknown>
}) {
  const [label, setLabel] = useState<string>('')
  const [code, setCode] = useState<string>('')
  const [codeType, setCodeType] = useState<CreateCodeTypeOption>('permanent')
  const [startAtLocal, setStartAtLocal] = useState<string>('')
  const [endAtLocal, setEndAtLocal] = useState<string>('')
  const [days, setDays] = useState<Set<number>>(() => daysMaskToSet(DEFAULT_DAYS_MASK))
  const [windowStart, setWindowStart] = useState<string>('')
  const [windowEnd, setWindowEnd] = useState<string>('')
  const [allowedStates, setAllowedStates] = useState<AlarmStateType[]>(opts.armableStates)
  const [reauthPassword, setReauthPassword] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setLabel('')
    setCode('')
    setCodeType('permanent')
    setStartAtLocal('')
    setEndAtLocal('')
    setDays(daysMaskToSet(DEFAULT_DAYS_MASK))
    setWindowStart('')
    setWindowEnd('')
    setAllowedStates(opts.armableStates)
    setReauthPassword('')
    setError(null)
  }

  const submit = async () => {
    setError(null)
    if (!opts.userId) {
      setError('Select a user first.')
      return
    }
    const codeErr = validateDigitsPin(code, { label: 'Code', required: false })
    if (codeErr) {
      setError(codeErr)
      return
    }
    if (!reauthPassword.trim()) {
      setError('Password is required for re-authentication.')
      return
    }

    const isTemporary = codeType === 'temporary'
    const startAt = isTemporary ? toUtcIsoFromDatetimeLocal(startAtLocal) : null
    const endAt = isTemporary ? toUtcIsoFromDatetimeLocal(endAtLocal) : null
    if (isTemporary && startAt && endAt && startAt > endAt) {
      setError('Active until must be after active from.')
      return
    }

    const daysOfWeek = isTemporary ? daysSetToMask(days) : null
    if (isTemporary && daysOfWeek === 0) {
      setError('Select at least one day.')
      return
    }

    const { windowStart: parsedStart, windowEnd: parsedEnd, error: windowError } = isTemporary
      ? parseOptionalTimeWindow(windowStart, windowEnd)
      : { windowStart: null, windowEnd: null, error: null }
    if (isTemporary && windowError) {
      setError(windowError)
      return
    }

    try {
      await opts.onCreate({
        userId: opts.userId,
        label: label.trim(),
        code: code.trim(),
        codeType,
        startAt,
        endAt,
        daysOfWeek,
        windowStart: parsedStart,
        windowEnd: parsedEnd,
        allowedStates,
        reauthPassword,
      })
      reset()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to create code')
    }
  }

  return {
    label,
    setLabel,
    code,
    setCode,
    codeType,
    setCodeType,
    startAtLocal,
    setStartAtLocal,
    endAtLocal,
    setEndAtLocal,
    days,
    setDays,
    windowStart,
    setWindowStart,
    windowEnd,
    setWindowEnd,
    allowedStates,
    setAllowedStates,
    reauthPassword,
    setReauthPassword,
    error,
    isTemporary: codeType === 'temporary',
    submit,
  }
}

