import type { DoorCode } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

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
    return (
      <div className="flex items-center gap-2">
        <Badge variant="destructive" title={code.lastPushError || undefined}>
          {clearing ? 'Clear failed' : 'Push failed'}
          {code.lastPushError ? `: ${code.lastPushError.slice(0, 80)}` : ''}
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

  // pending, or pushed with a clear the scheduler hasn't got to yet
  const waiting = clearing ? 'Waiting for the lock to clear the slot.' : 'Waiting for the lock to accept the code.'
  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" title={code.lastPushError || waiting}>
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
