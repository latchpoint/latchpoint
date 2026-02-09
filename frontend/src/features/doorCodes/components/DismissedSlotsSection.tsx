import { useState } from 'react'
import { getErrorMessage } from '@/types/errors'
import { useDismissedAssignmentsQuery, useUndismissAssignmentMutation } from '@/hooks/useDoorCodesQueries'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'

type Props = {
  lockEntityId: string
}

export function DismissedSlotsSection({ lockEntityId }: Props) {
  const dismissedQuery = useDismissedAssignmentsQuery(lockEntityId)
  const undismissMutation = useUndismissAssignmentMutation(lockEntityId)
  const [reauthPassword, setReauthPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const handleUndismiss = async (assignmentId: number) => {
    setError(null)
    if (!reauthPassword.trim()) {
      setError('Password is required for re-authentication.')
      return
    }
    try {
      await undismissMutation.mutateAsync({ assignmentId, reauthPassword })
      setReauthPassword('')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to re-enable sync for this slot.')
    }
  }

  if (dismissedQuery.isLoading) return <LoadingInline label="Loading dismissed slots..." />
  if (dismissedQuery.isError)
    return (
      <Alert variant="error" layout="inline">
        <AlertDescription>{getErrorMessage(dismissedQuery.error)}</AlertDescription>
      </Alert>
    )

  const dismissed = dismissedQuery.data || []
  if (dismissed.length === 0) return null

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium">Dismissed Synced Slots</div>
      <p className="text-sm text-muted-foreground">
        These slots were previously synced but then deleted. They are skipped during sync. Re-enable sync to include
        them again.
      </p>

      {dismissed.map((assignment) => (
        <div key={assignment.id} className="flex items-center justify-between gap-3 rounded-md border border-input p-3 text-sm">
          <div>
            <span className="font-medium">Slot {assignment.slotIndex ?? '?'}</span>
            {assignment.doorCodeLabel ? <span className="ml-2 text-muted-foreground">{assignment.doorCodeLabel}</span> : null}
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={undismissMutation.isPending || !reauthPassword.trim()}
            onClick={() => handleUndismiss(assignment.id)}
          >
            {undismissMutation.isPending ? 'Re-enabling...' : 'Re-enable Sync'}
          </Button>
        </div>
      ))}

      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="dismissed-reauth-password">
          Password (required)
        </label>
        <Input
          id="dismissed-reauth-password"
          type="password"
          value={reauthPassword}
          onChange={(e) => setReauthPassword(e.target.value)}
          placeholder="Re-authentication password"
          disabled={undismissMutation.isPending}
        />
      </div>

      {error ? (
        <Alert variant="error" layout="inline">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}
