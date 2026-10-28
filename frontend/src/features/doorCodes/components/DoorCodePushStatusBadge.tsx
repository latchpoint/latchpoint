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

export function DoorCodePushStatusBadge({ code, lockNameByEntityId, canRetry, isRetrying, onRetry }: Props) {
  if (!code.lockEntityIds?.length) return null

  // An inactive code that holds no slot isn't on any of its locks. A failed one
  // falls through so a failed slot clear still shows as Push failed.
  if (
    !code.isActive &&
    code.pushState !== 'failed' &&
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

  // The backend refuses to push an inactive code, so don't offer Retry for one.
  const showRetry = canRetry && code.isActive

  if (code.pushState === 'pushed') {
    const slotDesc = describeSlots(code, lockNameByEntityId)
    return (
      <Badge variant="secondary" title={slotDesc || undefined}>
        On lock{slotDesc ? `: ${slotDesc}` : ''}
      </Badge>
    )
  }

  if (code.pushState === 'failed') {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="destructive" title={code.lastPushError || undefined}>
          Push failed{code.lastPushError ? `: ${code.lastPushError.slice(0, 80)}` : ''}
        </Badge>
        {showRetry ? (
          <Button size="sm" variant="secondary" disabled={isRetrying} onClick={onRetry}>
            {isRetrying ? 'Retrying…' : 'Retry'}
          </Button>
        ) : null}
        {!code.isActive ? (
          <span className="text-xs text-muted-foreground">(saving it as off again or deleting it retries the clear)</span>
        ) : null}
      </div>
    )
  }

  // pending
  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" title={code.lastPushError || 'Waiting for the lock to accept the code.'}>
        Pending sync
      </Badge>
      {showRetry ? (
        <Button size="sm" variant="ghost" disabled={isRetrying} onClick={onRetry}>
          {isRetrying ? 'Retrying…' : 'Retry now'}
        </Button>
      ) : null}
    </div>
  )
}
