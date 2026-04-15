import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDaysMask } from '@/features/codes/utils/daysOfWeek'
import { DoorCodeEditContainer } from '@/features/doorCodes/components/DoorCodeEditContainer'

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
  onBeginEdit: () => void
  onCloseEdit: () => void
  onUpdate: (id: number, req: UpdateDoorCodeRequest) => Promise<unknown>
  onDelete: (id: number, reauthPassword: string) => Promise<unknown>
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
  onBeginEdit,
  onCloseEdit,
  onUpdate,
  onDelete,
}: Props) {
  const [pinVisible, setPinVisible] = useState(false)

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
