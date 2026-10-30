import type { DoorCode } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { isLockAwaitingPush, isLockQueued } from '@/hooks/useDoorCodesQueries'

type Props = {
  code: DoorCode
  lockNameByEntityId: Map<string, string>
  canRetry: boolean
  isRetrying: boolean
  onRetry: () => void
}

function describeSlots(code: DoorCode, lockNameByEntityId: Map<string, string>): string {
  const pushed = code.lockSlotAssignments.filter((a) => a.slotIndex != null)
  if (!pushed.length) return ''
  return pushed
    .map((a) => `${lockNameByEntityId.get(a.lockEntityId) || a.lockEntityId} (slot ${a.slotIndex})`)
    .join(', ')
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

// A code is failed when any of its locks is, even while the scheduler still
// retries another (#126). Names both, or '' when that isn't the case (the
// clear-retry cap, or an API without per-lock state).
function describeFailedWhileRetrying(code: DoorCode, lockNameByEntityId: Map<string, string>): string {
  const assignments = code.lockSlotAssignments.filter((a) => !a.pendingRemoval)
  const failed = assignments.filter((a) => a.pushState === 'failed')
  const retrying = assignments.filter((a) => a.pushState != null && isLockAwaitingPush(code, a))
  if (!failed.length || !retrying.length) return ''
  const nameOf = (a: { lockEntityId: string }) => lockNameByEntityId.get(a.lockEntityId) || a.lockEntityId
  return `Push failed on ${joinNames(failed.map(nameOf))}, still retrying ${joinNames(retrying.map(nameOf))}`
}

// The errors of the locks that aren't queued, as "Back Door: Lock timed out",
// picked like the backend picks the ones in the code's lastPushError: not
// being dropped, and not pushed or still needing its set or schedule. A queued
// lock's own error is from the push before the save, so it's left out.
function otherLockErrors(
  code: DoorCode,
  queued: DoorCode['lockSlotAssignments'],
  nameOf: (a: { lockEntityId: string }) => string,
): string {
  return code.lockSlotAssignments
    .filter(
      (a) =>
        !queued.includes(a) &&
        !a.pendingRemoval &&
        !!a.lastPushError &&
        (a.pushState !== 'pushed' || a.slotIndex == null || !!a.schedulePending),
    )
    .map((a) => `${nameOf(a)}: ${a.lastPushError}`)
    .join('; ')
}

// The backend never pushes an inactive code. pendingSlotClears lists the slots
// it still has to clear for one (#151): a clear that failed, a slot the code
// still holds, or an unconfirmed slot left to check. The scheduler and Retry
// clear those, so an inactive manual code with any shows Pending clear (Clear
// failed once the clear hit the attempt cap), whatever its push state. An
// inactive code without any gets no Retry, since Retry would only come back
// with a 409.
export function DoorCodePushStatusBadge({ code, lockNameByEntityId, canRetry, isRetrying, onRetry }: Props) {
  // Synced codes don't count. Their slots are the lock's own and lock sync turns
  // them off without touching push_state (#149), so Retry would only 409.
  const clearing = !code.isActive && code.source !== 'synced' && (code.pendingSlotClears?.length ?? 0) > 0
  if (!code.lockEntityIds?.length && !clearing) return null

  // An active code is only on its locks from its start to its end (#145). The
  // scheduler pushes it at the start and turns it off at the end, so neither
  // gets a Retry, except a scheduled code whose clear hit the attempt cap: only
  // Retry clears that. Once it's off the states below take over.
  const multiLock = (code.lockEntityIds?.length ?? 0) > 1
  if (code.isActive && code.validity === 'scheduled') {
    const pendingClears = (code.pendingSlotClears?.length ?? 0) > 0
    if (code.pushState === 'failed' && pendingClears) {
      return (
        <div className="flex items-center gap-2">
          <Badge variant="destructive" title={code.lastPushError || undefined}>
            Clear failed
            {code.lastPushError ? `: ${code.lastPushError.slice(0, 80)}` : ''}
          </Badge>
          {canRetry ? (
            <Button size="sm" variant="secondary" disabled={isRetrying} onClick={onRetry}>
              {isRetrying ? 'Retrying…' : 'Retry'}
            </Button>
          ) : null}
          <span className="text-xs text-muted-foreground">
            (scheduled, the PIN may still be on a lock before its start, Retry tries the clear again)
          </span>
        </div>
      )
    }
    const stillOnALock = code.lockSlotAssignments.some((a) => a.slotIndex != null) || pendingClears
    const startsAt = code.startAt ? new Date(code.startAt).toLocaleString() : 'its start'
    return (
      <div className="flex items-center gap-2">
        <Badge variant="outline" title={code.lastPushError || undefined}>
          Scheduled
        </Badge>
        <span className="text-xs text-muted-foreground">
          {stillOnALock
            ? `(taking it off ${multiLock ? 'its locks' : 'the lock'} until ${startsAt})`
            : `(goes on ${multiLock ? 'its locks' : 'lock'} at ${startsAt})`}
        </span>
      </div>
    )
  }
  if (code.isActive && code.validity === 'expired') {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="outline" title={code.lastPushError || undefined}>
          Expired
        </Badge>
        <span className="text-xs text-muted-foreground">
          {`(removing from ${multiLock ? 'its locks' : 'lock'})`}
        </span>
      </div>
    )
  }

  if (code.pushState === 'pushed' && !clearing) {
    if (
      !code.isActive &&
      code.lockSlotAssignments.length > 0 &&
      code.lockSlotAssignments.every((a) => a.slotIndex == null)
    ) {
      return (
        <div className="flex items-center gap-2">
          <Badge variant="outline">Not on lock</Badge>
          <span className="text-xs text-muted-foreground">(inactive, no slot on any of its locks)</span>
        </div>
      )
    }
    const slotDesc = describeSlots(code, lockNameByEntityId)
    return (
      <Badge variant="secondary" title={slotDesc || undefined}>
        On lock{slotDesc ? `: ${slotDesc}` : ''}
      </Badge>
    )
  }

  const showRetry = canRetry && (code.isActive || clearing)

  if (code.pushState === 'failed') {
    // Each lock's chip has its own error, so this one doesn't repeat them.
    const failedWhileRetrying = code.isActive && !clearing ? describeFailedWhileRetrying(code, lockNameByEntityId) : ''
    return (
      <div className="flex items-center gap-2">
        <Badge variant="destructive" title={code.lastPushError || undefined}>
          {failedWhileRetrying || (
            <>
              {clearing ? 'Clear failed' : 'Push failed'}
              {code.lastPushError ? `: ${code.lastPushError.slice(0, 80)}` : ''}
            </>
          )}
        </Badge>
        {showRetry ? (
          <Button size="sm" variant="secondary" disabled={isRetrying} onClick={onRetry}>
            {isRetrying ? 'Retrying…' : 'Retry'}
          </Button>
        ) : null}
        {clearing ? (
          <span className="text-xs text-muted-foreground">
            (the PIN may still be on a lock, Retry tries the clear again)
          </span>
        ) : null}
      </div>
    )
  }

  // pending, or pushed with a clear the scheduler hasn't got to yet. A save or
  // Retry only queues the push now (#124), so while one is queued it says it's
  // being sent rather than repeating an error from before the save. The other
  // locks' errors still count (#205), so it goes on with those.
  const queued = clearing ? [] : code.lockSlotAssignments.filter((a) => isLockQueued(code, a))
  const nameOf = (a: { lockEntityId: string }) => lockNameByEntityId.get(a.lockEntityId) || a.lockEntityId
  const waiting = clearing
    ? 'Waiting for the lock to clear the slot.'
    : queued.length
      ? `Being sent to ${joinNames(queued.map(nameOf))}.`
      : 'Waiting for the lock to accept the code.'
  const title = queued.length
    ? [waiting, otherLockErrors(code, queued, nameOf)].filter(Boolean).join(' ')
    : code.lastPushError || waiting
  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" title={title}>
        {clearing ? 'Pending clear' : 'Pending sync'}
      </Badge>
      {showRetry ? (
        <Button size="sm" variant="ghost" disabled={isRetrying} onClick={onRetry}>
          {isRetrying ? 'Retrying…' : 'Retry now'}
        </Button>
      ) : null}
      {clearing ? (
        <span className="text-xs text-muted-foreground">(the PIN may still be on a lock, retried automatically)</span>
      ) : null}
    </div>
  )
}
