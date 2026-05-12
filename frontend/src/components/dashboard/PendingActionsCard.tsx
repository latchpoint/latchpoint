/**
 * PendingActionsCard — dashboard surface for the ADR-0091 PendingAction queue.
 *
 * Shows currently-scheduled rule actions with a live countdown and a per-row
 * Cancel button. Renders nothing when the queue is empty so the dashboard
 * stays uncluttered.
 */
import { useEffect, useState } from 'react'
import { Clock, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  usePendingActionsQuery,
  useCancelPendingActionMutation,
} from '@/hooks/useAlarmQueries'
import type { PendingAction } from '@/types'

function actionLabel(pa: PendingAction): string {
  const payload = pa.actionPayload as { type?: string; providerId?: string }
  switch (payload?.type) {
    case 'alarm_trigger':
      return 'Trigger alarm'
    case 'send_notification':
      return 'Send notification'
    default:
      return String(payload?.type ?? 'Action')
  }
}

function useSecondsUntil(isoTimestamp: string): number {
  // Use ceil so a row with 0.4s remaining still reads "1s" — keeps the
  // countdown monotonic and avoids flashing "0s" while the row is still
  // scheduled (the fire-task hasn't ticked yet).
  const compute = () => Math.max(0, Math.ceil((new Date(isoTimestamp).getTime() - Date.now()) / 1000))
  const [seconds, setSeconds] = useState<number>(compute)
  useEffect(() => {
    const id = setInterval(() => setSeconds(compute()), 1000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isoTimestamp])
  return seconds
}

function PendingActionRow({ pa, onCancel, disabled }: { pa: PendingAction; onCancel: () => void; disabled: boolean }) {
  const remaining = useSecondsUntil(pa.fireAt)
  return (
    <div className="flex items-center gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <Clock className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium leading-tight">{actionLabel(pa)}</div>
        <div className="truncate text-xs text-muted-foreground">
          Rule: <span className="font-mono">{pa.ruleName}</span> · in <strong>{remaining}s</strong>
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onCancel}
        disabled={disabled}
        aria-label="Cancel pending action"
        className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  )
}

export function PendingActionsCard() {
  const pendingQuery = usePendingActionsQuery()
  const cancel = useCancelPendingActionMutation()
  const rows = pendingQuery.data ?? []
  // Track per-row cancel-in-flight so a long mutation on row N doesn't
  // disable cancellation of row M.
  const pendingRowId = cancel.isPending ? (cancel.variables ?? null) : null

  if (rows.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pending Actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.map((pa) => (
          <PendingActionRow
            key={pa.id}
            pa={pa}
            onCancel={() => cancel.mutate(pa.id)}
            disabled={pendingRowId === pa.id}
          />
        ))}
      </CardContent>
    </Card>
  )
}
