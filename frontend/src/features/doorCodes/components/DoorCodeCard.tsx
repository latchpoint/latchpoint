import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/types'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDaysMask } from '@/features/codes/utils/daysOfWeek'
import { DoorCodeEditContainer } from '@/features/doorCodes/components/DoorCodeEditContainer'
import { DoorCodePushStatusBadge } from '@/features/doorCodes/components/DoorCodePushStatusBadge'

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
}

// What a Retry error is about. When this changes the error is out of date.
function pushStateKeyOf(code: DoorCode): string {
  return `${code.isActive}|${code.pushState}|${code.lastPushAttemptAt ?? ''}`
}

function LockBadges({ lockEntityIds, lockNameByEntityId }: { lockEntityIds: string[]; lockNameByEntityId: Map<string, string> }) {
  if (!lockEntityIds.length) return <span className="text-sm text-muted-foreground">No locks</span>
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {lockEntityIds.map((entityId) => (
        <Badge key={entityId} variant="outline">
          {lockNameByEntityId.get(entityId) || entityId}
        </Badge>
      ))}
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
}: Props) {
  const queryClient = useQueryClient()
  const [pinVisible, setPinVisible] = useState(false)
  // stateKey is the push state the error belongs to. caughtUp turns true once
  // this card's props show that state.
  const [retryError, setRetryError] = useState<{ message: string; stateKey: string; caughtUp: boolean } | null>(
    null,
  )
  const alertRef = useRef<HTMLDivElement>(null)
  const retryFocusRef = useRef<Element | null>(null)

  const pushStateKey = pushStateKeyOf(code)

  // Once the card shows the state the error belongs to, any change after that
  // (the code is turned back on, the scheduler pushes it) means it no longer applies.
  if (retryError) {
    if (retryError.stateKey === pushStateKey) {
      if (!retryError.caughtUp) setRetryError({ ...retryError, caughtUp: true })
    } else if (retryError.caughtUp) {
      setRetryError(null)
    }
  }
  const visibleRetryError =
    retryError && (!retryError.caughtUp || retryError.stateKey === pushStateKey) ? retryError.message : null

  // A refused Retry refetches the code, which can remove the focused Retry
  // button. Move focus to the error instead of dropping it on the page.
  useEffect(() => {
    if (!visibleRetryError || !retryFocusRef.current || retryFocusRef.current.isConnected) return
    retryFocusRef.current = null
    alertRef.current?.focus()
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
      const latest =
        queryClient
          .getQueryData<DoorCode[]>(queryKeys.doorCodes.byUser(code.userId))
          ?.find((c) => c.id === code.id) ?? code
      setRetryError({
        message: getErrorMessage(err) || 'Failed to retry push',
        stateKey: pushStateKeyOf(latest),
        caughtUp: false,
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
          <LockBadges lockEntityIds={code.lockEntityIds || []} lockNameByEntityId={lockNameByEntityId} />
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
