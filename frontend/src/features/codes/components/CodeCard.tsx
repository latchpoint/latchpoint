import { AlarmStateLabels, type AlarmStateType } from '@/lib/constants'
import type { AlarmCode } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CodeEditPanel } from '@/features/codes/components/CodeEditPanel'
import { formatDaysMask } from '@/features/codes/utils/daysOfWeek'
import type { UpdateCodeRequest } from '@/types'

type Props = {
  code: AlarmCode
  armableStates: AlarmStateType[]
  canManage: boolean
  isEditing: boolean
  isPending: boolean
  onBeginEdit: () => void
  onCancelEdit: () => void
  onUpdate: (id: number, req: UpdateCodeRequest) => Promise<unknown>
}

export function CodeCard({
  code,
  armableStates,
  canManage,
  isEditing,
  isPending,
  onBeginEdit,
  onCancelEdit,
  onUpdate,
}: Props) {
  return (
    <div className="rounded-md border border-input p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="font-medium">{code.label || 'Untitled code'}</div>
            <Badge variant={code.isActive ? 'secondary' : 'outline'}>{code.isActive ? 'Active' : 'Inactive'}</Badge>
          </div>
          <div className="text-sm text-muted-foreground">
            PIN length: {code.pinLength} • Type: {code.codeType}
          </div>
          {code.codeType === 'temporary' && (
            <div className="text-sm text-muted-foreground">
              Days: {formatDaysMask(code.daysOfWeek ?? 127)}
              {code.windowStart && code.windowEnd ? ` • Time: ${code.windowStart}–${code.windowEnd}` : ''}
            </div>
          )}
          {code.codeType === 'temporary' && (code.startAt || code.endAt) && (
            <div className="text-sm text-muted-foreground">
              Active window: {code.startAt ? new Date(code.startAt).toLocaleString() : '—'} →{' '}
              {code.endAt ? new Date(code.endAt).toLocaleString() : '—'}
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {(code.allowedStates || []).length === 0 ? (
              <span className="text-sm text-muted-foreground">No allowed arm states</span>
            ) : (
              code.allowedStates.map((state) => (
                <Badge key={state} variant="outline">
                  {AlarmStateLabels[state] || state}
                </Badge>
              ))
            )}
          </div>
        </div>

        {canManage && (
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={onBeginEdit}>
              Edit
            </Button>
          </div>
        )}
      </div>

      {canManage && isEditing && (
        <div className="mt-4">
          <CodeEditPanel
            code={code}
            armableStates={armableStates}
            isPending={isPending}
            onUpdate={onUpdate}
            onCancel={onCancelEdit}
          />
        </div>
      )}
    </div>
  )
}

