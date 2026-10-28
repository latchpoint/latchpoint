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

// The backend never pushes an inactive code, and it only leaves one pushed once
// no slot clear is outstanding (#144). So for an inactive manual code, pending
// means a clear that may have left the PIN on a lock is still being retried by
// the scheduler (a refused delete ends here too), and failed means that clear
// hit the attempt cap. Retry retries the clear in both.
export function DoorCodePushStatusBadge({ code, lockNameByEntityId, canRetry, isRetrying, onRetry }: Props) {
  if (!code.lockEntityIds?.length) return null

  if (code.pushState === 'pushed') {
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

  // Synced codes don't count. Lock sync creates them at the default pending and
  // turns them off without touching push_state, so for those pending says
  // nothing about a clear (#149). An inactive synced code gets the plain badge
  // with no Retry, since Retry would only come back with a 409.
  const clearing = !code.isActive && code.source !== 'synced'
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

  // pending
  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" title={code.lastPushError || 'Waiting for the lock to accept the code.'}>
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
