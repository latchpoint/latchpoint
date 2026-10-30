import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'
import type { CachedDoorCode } from '@/hooks/useDoorCodesQueries'
import { getErrorMessage } from '@/types/errors'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDaysMask } from '@/features/codes/utils/daysOfWeek'
import { DoorCodeEditContainer } from '@/features/doorCodes/components/DoorCodeEditContainer'
import { DoorCodePushStatusBadge } from '@/features/doorCodes/components/DoorCodePushStatusBadge'
import { MAX_USES_ENFORCED } from '@/features/doorCodes/utils/maxUses'

type Props = {
  code: DoorCode
  canManage: boolean
  isEditing: boolean
  lockNameByEntityId: Map<string, string>
  locks: Entity[]
  locksIsLoading: boolean
  locksError: unknown
  isSaving: boolean
  isDeleting: boolean
  isRetryingPush: boolean
  onBeginEdit: () => void
  onCloseEdit: () => void
  onUpdate: (id: number, req: UpdateDoorCodeRequest) => Promise<unknown>
  onDelete: (id: number, reauthPassword: string) => Promise<unknown>
  onRetryPush: (id: number) => Promise<unknown>
  /** When the door codes `code` came from were fetched. */
  codesUpdatedAt: number
  /** Reads a code from the door codes cache, which can be ahead of `code` right after a mutation. */
  readCachedCode: (id: number) => CachedDoorCode | null
}

// What a Retry error is about. When this changes the error is out of date. A
// lock can land or fail while the code stays failed (#126), so each lock's
// state counts too.
function pushStateKeyOf(code: DoorCode): string {
  const locks = (code.lockSlotAssignments ?? [])
    .map((a) => `${a.lockEntityId}:${a.pushState ?? ''}:${a.schedulePending ? 1 : 0}`)
    .sort()
    .join(',')
  return `${code.isActive}|${code.pushState}|${code.lastPushAttemptAt ?? ''}|${locks}`
}

type LockChip = { suffix: string; title?: string; failed?: boolean }

function slotsText(slots: number[]): string {
  return slots.length === 1 ? `Slot ${slots[0]}` : `Slots ${slots.join(', ')}`
}

// What one lock's chip says (#126, #123). Its own push state only means
// something while the code is on its locks, ie active and between its start
// and end; the code-level badge covers the rest. A slot still to clear shows
// whatever the code's state, so a lock never looks settled while it may still
// hold a PIN (PR #196 review).
function lockChipOf(code: DoorCode, lockEntityId: string): LockChip {
  const assignments = code.lockSlotAssignments ?? []
  const assignment = assignments.find((a) => a.lockEntityId === lockEntityId)
  // Still listed until its slot clear works (#151).
  if (assignment?.pendingRemoval) return { suffix: ' (removing)' }

  const onItsLocks = code.isActive && code.validity !== 'scheduled' && code.validity !== 'expired'
  const pushState = onItsLocks ? assignment?.pushState : undefined
  if (assignment && pushState === 'failed') {
    const count = assignment.pushAttemptCount ?? 0
    // The attempt cap can fail a lock with no error of its own (a busy lock).
    const fallback = `${count > 0 ? `Push gave up after ${count} attempts` : 'Push failed'}, Retry sends it again.`
    return {
      suffix: assignment.schedulePending ? ' (schedule not applied)' : ' (push failed)',
      title: assignment.lastPushError || fallback,
      failed: true,
    }
  }

  // Synced codes don't count once off, like the code-level badge: lock sync
  // turns them off and their slots are the lock's own (#149).
  const clearSlots =
    code.isActive || code.source !== 'synced'
      ? (code.pendingSlotClears ?? []).filter((c) => c.lockEntityId === lockEntityId).map((c) => c.slotIndex)
      : []
  if (clearSlots.length) {
    // A failed code with no failed lock is failed by the clear-retry cap.
    const lockFailed = onItsLocks && assignments.some((a) => !a.pendingRemoval && a.pushState === 'failed')
    if (code.pushState === 'failed' && !lockFailed) {
      return {
        suffix: ' (clear failed)',
        title: `${slotsText(clearSlots)} may still hold the PIN, Retry tries the clear again.`,
        failed: true,
      }
    }
    return { suffix: ' (clearing)', title: `${slotsText(clearSlots)} may still hold the PIN, retried automatically.` }
  }

  if (assignment && pushState === 'pending') {
    if (assignment.schedulePending) {
      // Still being retried. Only a failed one is "not applied".
      return {
        suffix: ' (schedule pending)',
        title: assignment.lastPushError || 'The PIN is on the lock, its schedule is still being sent.',
      }
    }
    return { suffix: ' (pending)', title: assignment.lastPushError || 'Waiting for the lock to accept the code.' }
  }
  return { suffix: '' }
}

function LockBadges({ code, lockNameByEntityId }: { code: DoorCode; lockNameByEntityId: Map<string, string> }) {
  const lockEntityIds = code.lockEntityIds || []
  if (!lockEntityIds.length) return <span className="text-sm text-muted-foreground">No locks</span>
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {lockEntityIds.map((entityId) => {
        const chip = lockChipOf(code, entityId)
        return (
          <Badge key={entityId} variant={chip.failed ? 'destructive' : 'outline'} title={chip.title}>
            {lockNameByEntityId.get(entityId) || entityId}
            {chip.suffix}
          </Badge>
        )
      })}
    </div>
  )
}

export function DoorCodeCard({
  code,
  canManage,
  isEditing,
  lockNameByEntityId,
  locks,
  locksIsLoading,
  locksError,
  isSaving,
  isDeleting,
  isRetryingPush,
  onBeginEdit,
  onCloseEdit,
  onUpdate,
  onDelete,
  onRetryPush,
  codesUpdatedAt,
  readCachedCode,
}: Props) {
  const [pinVisible, setPinVisible] = useState(false)
  // stateKey is the push state the error belongs to, as of the codes fetched at
  // dataUpdatedAt.
  const [retryError, setRetryError] = useState<{ message: string; stateKey: string; dataUpdatedAt: number } | null>(
    null,
  )
  const alertRef = useRef<HTMLDivElement>(null)
  const retryFocusRef = useRef<Element | null>(null)

  // Once the card shows codes at least as new as the ones the error was pinned
  // to, a different push state (turned back on, pushed by the scheduler) means
  // the error no longer applies.
  const retryErrorIsStale =
    retryError != null && codesUpdatedAt >= retryError.dataUpdatedAt && retryError.stateKey !== pushStateKeyOf(code)
  if (retryErrorIsStale) setRetryError(null)
  const visibleRetryError = retryError && !retryErrorIsStale ? retryError.message : null

  // A refused Retry refetches the code, which can remove the focused Retry
  // button. Move focus to the error then, but only if focus was dropped on the
  // page rather than moved somewhere else while the Retry ran.
  useEffect(() => {
    const retryButton = retryFocusRef.current
    if (!visibleRetryError || !retryButton || retryButton.isConnected) return
    retryFocusRef.current = null
    const active = document.activeElement
    if (active == null || active === document.body) alertRef.current?.focus()
  })

  const handleRetryPush = async () => {
    retryFocusRef.current = document.activeElement
    setRetryError(null)
    try {
      await onRetryPush(code.id)
    } catch (err) {
      // The Retry mutation refetches the codes before it rejects, so the cache
      // already has the state this error belongs to (e.g. the code turned off
      // elsewhere) even though this card's props haven't caught up yet.
      const latest = readCachedCode(code.id)
      setRetryError({
        message: getErrorMessage(err) || 'Failed to retry push',
        stateKey: pushStateKeyOf(latest?.code ?? code),
        dataUpdatedAt: latest?.dataUpdatedAt ?? codesUpdatedAt,
      })
    }
  }

  const pinDisplay = code.pin != null
    ? (pinVisible ? code.pin : '•'.repeat(code.pin.length))
    : 'unknown'
  const canTogglePin = code.pin != null

  return (
    <div className="rounded-md border border-input p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="font-medium">{code.label || 'Untitled door code'}</div>
            <Badge variant={code.isActive ? 'secondary' : 'outline'}>{code.isActive ? 'Active' : 'Inactive'}</Badge>
            {code.source === 'synced' ? <Badge variant="outline">Synced</Badge> : null}
            {/* Says why an expired code is off; the push badge covers an active one (#145). */}
            {code.validity === 'expired' && !code.isActive ? <Badge variant="outline">Expired</Badge> : null}
          </div>
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <span>PIN: {pinDisplay}</span>
            {canTogglePin ? (
              <button
                type="button"
                className="inline-flex items-center text-muted-foreground hover:text-foreground"
                onClick={() => setPinVisible(!pinVisible)}
                aria-label={pinVisible ? 'Hide PIN' : 'Show PIN'}
              >
                {pinVisible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              </button>
            ) : null}
            <span> • Type: {code.codeType}</span>
            {code.maxUses != null ? <span> • Max uses: {code.maxUses}</span> : null}
          </div>
          {code.maxUses != null && !MAX_USES_ENFORCED ? (
            <div className="text-xs text-muted-foreground">Max uses isn't enforced yet</div>
          ) : null}
          {code.codeType === 'temporary' ? (
            <>
              <div className="text-sm text-muted-foreground">
                Days: {formatDaysMask(code.daysOfWeek ?? 127)}
                {code.windowStart && code.windowEnd ? ` • Time: ${code.windowStart}–${code.windowEnd}` : ''}
              </div>
              {(code.startAt || code.endAt) ? (
                <div className="text-sm text-muted-foreground">
                  Active window: {code.startAt ? new Date(code.startAt).toLocaleString() : '—'} →{' '}
                  {code.endAt ? new Date(code.endAt).toLocaleString() : '—'}
                </div>
              ) : null}
            </>
          ) : null}
          <div className="text-sm text-muted-foreground">
            Uses: {code.usesCount}
            {code.lastUsedAt ? ` • Last used: ${new Date(code.lastUsedAt).toLocaleString()}` : ''}
            {code.lastUsedLock ? ` • Lock: ${lockNameByEntityId.get(code.lastUsedLock) || code.lastUsedLock}` : ''}
          </div>
          <LockBadges code={code} lockNameByEntityId={lockNameByEntityId} />
          <div className="mt-2">
            <DoorCodePushStatusBadge
              code={code}
              lockNameByEntityId={lockNameByEntityId}
              canRetry={canManage}
              isRetrying={isRetryingPush}
              onRetry={handleRetryPush}
            />
          </div>
          {visibleRetryError ? (
            <Alert ref={alertRef} tabIndex={-1} variant="error" layout="inline" className="mt-2">
              <AlertDescription>{visibleRetryError}</AlertDescription>
            </Alert>
          ) : null}
        </div>

        {canManage ? (
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={onBeginEdit}>
              Edit
            </Button>
          </div>
        ) : null}
      </div>

      {canManage && isEditing ? (
        <DoorCodeEditContainer
          code={code}
          locks={locks}
          locksIsLoading={locksIsLoading}
          locksError={locksError}
          isSaving={isSaving}
          isDeleting={isDeleting}
          onClose={onCloseEdit}
          onUpdate={onUpdate}
          onDelete={onDelete}
        />
      ) : null}
    </div>
  )
}
