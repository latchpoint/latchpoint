import { useEffect, useState } from 'react'
import type { AlarmStateType } from '@/lib/constants'
import type { AlarmCode, UpdateCodeRequest } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Switch } from '@/components/ui/switch'
import { ActiveWindowPicker } from '@/features/codes/components/ActiveWindowPicker'
import { AllowedArmStatesPicker } from '@/features/codes/components/AllowedArmStatesPicker'
import { DaysOfWeekPicker } from '@/features/codes/components/DaysOfWeekPicker'
import { ReauthPasswordField } from '@/features/codes/components/ReauthPasswordField'
import { TimeWindowFields } from '@/features/codes/components/TimeWindowFields'
import { toDatetimeLocalValue, toUtcIsoFromDatetimeLocal } from '@/features/codes/utils/datetimeLocal'
import { daysMaskToSet, daysSetToMask } from '@/features/codes/utils/daysOfWeek'
import { parseOptionalTimeWindow, validateDigitsPin } from '@/features/codes/utils/validation'

type Props = {
  code: AlarmCode
  armableStates: AlarmStateType[]
  isPending: boolean
  onUpdate: (id: number, req: UpdateCodeRequest) => Promise<unknown>
  onCancel: () => void
}

export function CodeEditPanel({ code, armableStates, isPending, onUpdate, onCancel }: Props) {
  const [editLabel, setEditLabel] = useState<string>('')
  const [editNewCode, setEditNewCode] = useState<string>('')
  const [editIsActive, setEditIsActive] = useState<boolean>(true)
  const [editStartAtLocal, setEditStartAtLocal] = useState<string>('')
  const [editEndAtLocal, setEditEndAtLocal] = useState<string>('')
  const [editDays, setEditDays] = useState<Set<number>>(() => daysMaskToSet(127))
  const [editWindowStart, setEditWindowStart] = useState<string>('')
  const [editWindowEnd, setEditWindowEnd] = useState<string>('')
  const [editAllowedStates, setEditAllowedStates] = useState<AlarmStateType[]>([])
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
    setEditAllowedStates(code.allowedStates || [])
    setEditReauthPassword('')
    setEditError(null)
  }, [code])

  const submitEdit = async () => {
    setEditError(null)
    const codeErr = validateDigitsPin(editNewCode, { label: 'New code', required: false })
    if (codeErr) {
      setEditError(codeErr)
      return
    }
    if (!editReauthPassword.trim()) {
      setEditError('Password is required for re-authentication.')
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
    const req: UpdateCodeRequest = {
      label: editLabel.trim(),
      isActive: editIsActive,
      startAt,
      endAt,
      daysOfWeek,
      windowStart,
      windowEnd,
      allowedStates: editAllowedStates,
      reauthPassword: editReauthPassword,
    }
    if (editNewCode.trim()) req.code = editNewCode.trim()

    try {
      await onUpdate(code.id, req)
      onCancel()
    } catch (err) {
      setEditError(getErrorMessage(err) || 'Failed to update code')
    }
  }

  return (
    <div className="space-y-4 border-t border-input pt-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor={`edit-label-${code.id}`}>
            Label
          </label>
          <Input
            id={`edit-label-${code.id}`}
            value={editLabel}
            onChange={(e) => setEditLabel(e.target.value)}
            disabled={isPending}
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor={`edit-code-${code.id}`}>
            New code (optional)
          </label>
          <Input
            id={`edit-code-${code.id}`}
            value={editNewCode}
            onChange={(e) => setEditNewCode(e.target.value)}
            placeholder="4–8 digits"
            inputMode="numeric"
            autoComplete="off"
            disabled={isPending}
          />
        </div>
      </div>

      {code.codeType === 'temporary' && (
        <div className="space-y-4">
          <ActiveWindowPicker
            value={{ start: editStartAtLocal, end: editEndAtLocal }}
            onChange={(next) => {
              setEditStartAtLocal(next.start)
              setEditEndAtLocal(next.end)
            }}
            disabled={isPending}
            showHelper={false}
          />

          <DaysOfWeekPicker title="Days allowed" value={editDays} onChange={setEditDays} disabled={isPending} />

          <TimeWindowFields
            startId={`edit-window-start-${code.id}`}
            endId={`edit-window-end-${code.id}`}
            startValue={editWindowStart}
            endValue={editWindowEnd}
            onStartChange={setEditWindowStart}
            onEndChange={setEditWindowEnd}
            disabled={isPending}
            showHelp={false}
          />
        </div>
      )}

      <div className="space-y-2">
        <AllowedArmStatesPicker
          states={armableStates}
          value={editAllowedStates}
          onChange={setEditAllowedStates}
          disabled={isPending}
          helpTip="Controls which armed states this code is allowed to arm into."
        />
      </div>

      <div className="flex items-center gap-2">
        <Switch
          checked={editIsActive}
          onCheckedChange={setEditIsActive}
          disabled={isPending}
          aria-labelledby={`code-active-label-${code.id}`}
        />
        <span id={`code-active-label-${code.id}`} className="text-sm">
          Active
        </span>
      </div>

      <div className="space-y-2">
        <ReauthPasswordField
          id={`edit-password-${code.id}`}
          value={editReauthPassword}
          onChange={setEditReauthPassword}
          disabled={isPending}
          helpTip="Required to save changes to this code."
        />
      </div>

      {editError && (
        <Alert variant="error" layout="inline">
          <AlertDescription>{editError}</AlertDescription>
        </Alert>
      )}

      <div className="flex items-center justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
        <Button onClick={submitEdit} disabled={isPending}>
          {isPending ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}
