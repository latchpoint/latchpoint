import { useMemo, useState } from 'react'
import type { Entity, LockConfigSyncResult } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { useSyncLockConfigMutation } from '@/hooks/useDoorCodesQueries'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { formatDaysMask } from '@/features/codes/utils/daysOfWeek'

type Props = {
  userId: string
  locks: Entity[]
  locksIsLoading: boolean
  locksError: unknown
}

function getZwavejsNodeId(entity: Entity): number | null {
  const attrs = entity.attributes || {}
  const zw = (attrs as Record<string, unknown>).zwavejs
  if (!zw || typeof zw !== 'object') return null
  const nodeId = (zw as Record<string, unknown>).nodeId ?? (zw as Record<string, unknown>).node_id
  if (typeof nodeId === 'number' && Number.isFinite(nodeId)) return nodeId
  if (typeof nodeId === 'string' && /^\d+$/.test(nodeId)) return Number(nodeId)
  return null
}

function ResultSummary({ result }: { result: LockConfigSyncResult }) {
  return (
    <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
      <div>Created: {result.created}</div>
      <div>Updated: {result.updated}</div>
      <div>Unchanged: {result.unchanged}</div>
      <div>Deactivated: {result.deactivated}</div>
      <div>Dismissed: {result.dismissed}</div>
      <div>Skipped: {result.skipped}</div>
      <div>Errors: {result.errors}</div>
      <div>Node: {result.nodeId}</div>
    </div>
  )
}

export function LockConfigSyncCard({ userId, locks, locksIsLoading, locksError }: Props) {
  const syncMutation = useSyncLockConfigMutation()
  const [selectedLockEntityId, setSelectedLockEntityId] = useState<string>('')
  const [reauthPassword, setReauthPassword] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LockConfigSyncResult | null>(null)
  const [resultOpen, setResultOpen] = useState<boolean>(false)

  const zwaveLinkedLocks = useMemo(() => {
    return (locks || [])
      .filter((entity) => entity.domain === 'lock')
      .filter((entity) => getZwavejsNodeId(entity) != null)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [locks])

  const submit = async () => {
    setError(null)
    if (!userId) {
      setError('Select a user first.')
      return
    }
    if (!selectedLockEntityId) {
      setError('Select a lock.')
      return
    }
    if (!reauthPassword.trim()) {
      setError('Password is required for re-authentication.')
      return
    }

    try {
      const data = await syncMutation.mutateAsync({
        lockEntityId: selectedLockEntityId,
        req: { userId, reauthPassword },
      })
      setResult(data)
      setResultOpen(true)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync codes from lock.')
    } finally {
      setReauthPassword('')
    }
  }

  return (
    <div className="space-y-4">
      {locksIsLoading ? <LoadingInline label="Loading locks…" /> : null}
      {locksError ? (
        <Alert variant="error" layout="inline">
          <AlertDescription>Failed to load entities: {getErrorMessage(locksError) || 'Unknown error'}</AlertDescription>
        </Alert>
      ) : null}

      {!locksIsLoading && !locksError && zwaveLinkedLocks.length === 0 ? (
        <Alert variant="warning" layout="inline">
          <AlertDescription>
            No Z-Wave-linked lock entities found. Sync Home Assistant entities and ensure your lock entity exposes a
            Z-Wave `node_id` attribute.
          </AlertDescription>
        </Alert>
      ) : null}

      <FormField label="Lock" required>
        <Select
          value={selectedLockEntityId}
          onChange={(e) => setSelectedLockEntityId(e.target.value)}
          disabled={syncMutation.isPending || zwaveLinkedLocks.length === 0}
        >
          <option value="">Select a lock…</option>
          {zwaveLinkedLocks.map((lock) => (
            <option key={lock.entityId} value={lock.entityId}>
              {lock.name}
            </option>
          ))}
        </Select>
      </FormField>

      <FormField label="Password" required help="Required to sync door codes (admin re-authentication).">
        <Input
          type="password"
          value={reauthPassword}
          onChange={(e) => setReauthPassword(e.target.value)}
          disabled={syncMutation.isPending}
          placeholder="Re-authentication password"
        />
      </FormField>

      {error ? (
        <Alert variant="error" layout="inline">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex items-center gap-2">
        <Button onClick={() => void submit()} disabled={syncMutation.isPending || zwaveLinkedLocks.length === 0}>
          {syncMutation.isPending ? 'Syncing…' : 'Sync Codes from Lock'}
        </Button>
      </div>

      <Modal
        open={resultOpen}
        onOpenChange={setResultOpen}
        title="Sync Results"
        description={result?.lockEntityId ? `Lock: ${result.lockEntityId}` : undefined}
        maxWidthClassName="max-w-2xl"
      >
        {result ? (
          <div className="space-y-4">
            <ResultSummary result={result} />
            <div className="space-y-2">
              {(result.slots || [])
                .slice()
                .sort((a, b) => a.slotIndex - b.slotIndex)
                .map((slot) => (
                  <div key={slot.slotIndex} className="rounded-md border border-input p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-medium">
                        Slot {slot.slotIndex}: {slot.action}
                      </div>
                      <div className="text-muted-foreground">
                        {slot.pinKnown === false ? 'PIN unknown' : slot.pinKnown === true ? 'PIN known' : ''}
                      </div>
                    </div>
                    {slot.scheduleApplied && slot.schedule ? (
                      <div className="mt-1 text-muted-foreground">
                        Days: {formatDaysMask(slot.schedule.daysOfWeek)} • Time: {slot.schedule.windowStart}–{slot.schedule.windowEnd}
                      </div>
                    ) : null}
                    {slot.scheduleUnsupported ? (
                      <div className="mt-1 text-muted-foreground">Schedule: unsupported (not imported)</div>
                    ) : null}
                    {slot.warnings && slot.warnings.length > 0 ? (
                      <div className="mt-1 text-warning-foreground">
                        {slot.warnings.map((w) => (
                          <span key={w} className="mr-2 inline-block rounded bg-warning/20 px-1.5 py-0.5 text-xs">
                            {w}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {slot.error ? <div className="mt-1 text-destructive">{slot.error}</div> : null}
                  </div>
                ))}
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

export default LockConfigSyncCard

