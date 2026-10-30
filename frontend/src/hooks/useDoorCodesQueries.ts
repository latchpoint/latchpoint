import { useCallback } from 'react'
import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { doorCodesService, locksService } from '@/services'
import { queryKeys } from '@/types'
import type {
  CreateDoorCodeRequest,
  DoorCode,
  DoorCodeLockSlotAssignment,
  LockConfigSyncRequest,
  LockConfigSyncResult,
  UpdateDoorCodeRequest,
} from '@/types'

/** How often the door codes refetch while one is waiting on its locks. */
export const DOOR_CODES_SETTLING_POLL_MS = 15_000
/**
 * How often they refetch while one is settling right after a create, update or
 * Retry. Those only queue the push now and the scheduler sends it within a few
 * seconds (#124), so the card should pick that up sooner than the 15s poll.
 */
export const DOOR_CODES_FAST_POLL_MS = 2_000
/** How long after a create, update or Retry the fast poll lasts. */
export const DOOR_CODES_FAST_POLL_WINDOW_MS = 60_000

// When a create, update or Retry last worked, per query client and the user
// whose codes it changed. Kept off the query data so a refetch can't drop it,
// and per client so each test's client starts with none.
const lastPushRequestAtByClient = new WeakMap<QueryClient, Map<string, number>>()

function markPushRequested(queryClient: QueryClient, userId: string) {
  let byUser = lastPushRequestAtByClient.get(queryClient)
  if (!byUser) {
    byUser = new Map()
    lastPushRequestAtByClient.set(queryClient, byUser)
  }
  byUser.set(userId, Date.now())
}

/**
 * The door codes' refetch interval: the fast poll for a minute after a create,
 * update or Retry worked (`lastPushRequestAt`), the settling poll after that,
 * and none when nothing is settling.
 */
export function doorCodesRefetchInterval(
  codes: DoorCode[] | undefined,
  lastPushRequestAt: number | undefined,
  now: number = Date.now(),
): number | false {
  if (!codes?.some(isDoorCodeSettling)) return false
  if (lastPushRequestAt != null && now - lastPushRequestAt < DOOR_CODES_FAST_POLL_WINDOW_MS) {
    return DOOR_CODES_FAST_POLL_MS
  }
  return DOOR_CODES_SETTLING_POLL_MS
}

/**
 * Whether the scheduler still pushes to this lock of an active, started code:
 * it's `pending` and needs its `set` (no slot) or its schedule, matching
 * push_pending_door_codes' push arm (#126, #123). A `failed` lock waits for a
 * Retry, and a lock being dropped is never pushed. Nor is a slot whose clear is
 * still outstanding (a PIN change whose clear failed), since it may hold the
 * old PIN and the scheduler sends nothing to it until the clear works. Without
 * the per-lock fields (an API from before #196) it falls back to the code's own
 * state.
 */
export function isLockAwaitingPush(code: DoorCode, assignment: DoorCodeLockSlotAssignment): boolean {
  if (assignment.pendingRemoval) return false
  if (
    assignment.slotIndex != null &&
    (code.pendingSlotClears ?? []).some(
      (c) => c.lockEntityId === assignment.lockEntityId && c.slotIndex === assignment.slotIndex,
    )
  ) {
    return false
  }
  if (assignment.pushState == null) return code.pushState === 'pending' && assignment.slotIndex == null
  return assignment.pushState === 'pending' && (assignment.slotIndex == null || !!assignment.schedulePending)
}

/**
 * Whether a create, update or Retry queued a push of this lock that the
 * scheduler hasn't tried yet (#124). The request is used up by the first push
 * attempt on the lock after it, so it's queued while `lastPushAttemptAt` is
 * null or older than `pushRequestedAt`, the lock is `pending` and it still
 * needs a push. Only while the code is on its locks, ie active and between its
 * start and end, since the backend only queues those. Without
 * `pushRequestedAt` (an API from before #124) nothing is queued.
 */
export function isLockQueued(code: DoorCode, assignment: DoorCodeLockSlotAssignment): boolean {
  if (!assignment.pushRequestedAt || assignment.pushState !== 'pending') return false
  if (!code.isActive || code.validity === 'scheduled' || code.validity === 'expired') return false
  if (!isLockAwaitingPush(code, assignment)) return false
  if (!assignment.lastPushAttemptAt) return true
  return Date.parse(assignment.lastPushAttemptAt) < Date.parse(assignment.pushRequestedAt)
}

/**
 * Whether the scheduler is still working on `code`, matching what
 * push_pending_door_codes retries: a slot it still has to clear (#151), or an
 * active code with a lock still waiting on its `set` or schedule, even when the
 * code is failed because another of its locks is (#126). A lock queued by a
 * save or Retry (#124) is one of those, since it's pending and needs a push. A
 * failed code with no lock left waiting isn't, since only a Retry moves it. Nor is a
 * pending code the scheduler never picks up, like one lock sync created or an
 * active one with no locks. An active code that's expired is, since the
 * scheduler turns it off and clears it within a minute. A scheduled one is
 * while it still holds a slot or has a clear outstanding, since the scheduler
 * takes it off its locks until its start, and isn't once that's done, since it
 * only waits on the clock then. A scheduled code whose clear hit the attempt
 * cap isn't either, since only a Retry moves it (#145).
 */
export function isDoorCodeSettling(code: DoorCode): boolean {
  // Retired whatever its push state.
  if (code.isActive && code.validity === 'expired') return true
  const hasPendingClears = (code.pendingSlotClears?.length ?? 0) > 0
  if (code.isActive && code.validity === 'scheduled') {
    if (code.pushState === 'failed' && hasPendingClears) return false
    return hasPendingClears || (code.lockSlotAssignments ?? []).some((a) => a.slotIndex != null || a.pendingRemoval)
  }
  const lockAwaitingPush =
    code.isActive &&
    code.validity !== 'scheduled' &&
    (code.lockSlotAssignments ?? []).some((a) => isLockAwaitingPush(code, a))
  if (code.pushState === 'failed') return lockAwaitingPush
  if (hasPendingClears) return true
  if ((code.lockSlotAssignments ?? []).some((a) => a.pendingRemoval)) return true
  return lockAwaitingPush
}

export function useDoorCodesQuery(params: { userId: string; isAdmin: boolean }) {
  const { userId, isAdmin } = params
  const queryClient = useQueryClient()
  return useQuery<DoorCode[]>({
    queryKey: queryKeys.doorCodes.byUser(userId),
    queryFn: () => doorCodesService.getDoorCodes(isAdmin ? { userId } : undefined),
    enabled: !!userId,
    // Nothing pushes door code changes to the page (#156), so pick up changes
    // made in another tab or by the scheduler when the tab becomes visible
    // again (TanStack listens for visibilitychange), even inside the default
    // staleTime, and keep checking while a code is still settling. Faster for
    // a minute after a save or Retry, since that only queued the push (#124).
    // TanStack works this out again after every fetch, so the poll drops back
    // to 15s on the first fetch after the minute is up.
    refetchOnWindowFocus: 'always',
    refetchInterval: (query) =>
      doorCodesRefetchInterval(query.state.data, lastPushRequestAtByClient.get(queryClient)?.get(userId)),
  })
}

export type CachedDoorCode = { code: DoorCode; dataUpdatedAt: number }

/**
 * Returns a reader for one of `userId`'s door codes straight from the query
 * cache, along with when that data was fetched. For handlers that run before
 * the component re-renders with what a mutation just refetched.
 */
export function useReadCachedDoorCode(userId: string) {
  const queryClient = useQueryClient()
  return useCallback(
    (id: number): CachedDoorCode | null => {
      const state = queryClient.getQueryState<DoorCode[]>(queryKeys.doorCodes.byUser(userId))
      const code = state?.data?.find((c) => c.id === id)
      return state && code ? { code, dataUpdatedAt: state.dataUpdatedAt } : null
    },
    [queryClient, userId],
  )
}

export function useCreateDoorCodeMutation(targetUserId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (req: CreateDoorCodeRequest) => doorCodesService.createDoorCode(req),
    onSuccess: async () => {
      // Before the refetch, so the interval worked out after it is the fast one.
      markPushRequested(queryClient, targetUserId)
      await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.byUser(targetUserId) })
    },
  })
}

export function useUpdateDoorCodeMutation(targetUserId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: UpdateDoorCodeRequest }) =>
      doorCodesService.updateDoorCode(id, req),
    onSuccess: async () => {
      markPushRequested(queryClient, targetUserId)
      await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.byUser(targetUserId) })
    },
  })
}

export function useDeleteDoorCodeMutation(targetUserId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reauthPassword }: { id: number; reauthPassword: string }) =>
      doorCodesService.deleteDoorCode(id, { reauthPassword }),
    // Refetch on failure too: a delete refused because a slot couldn't be
    // cleared turns the code off, and the list should show that.
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.byUser(targetUserId) })
    },
  })
}

export function useRetryDoorCodePushMutation(targetUserId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => doorCodesService.retryPush(id),
    // Only a Retry that worked queued a push. A refused one (the 409s) is
    // still answered in the request, so it doesn't start the fast poll.
    onSuccess: () => {
      markPushRequested(queryClient, targetUserId)
    },
    // Refetch on failure too: a refused Retry (e.g. the code was turned off
    // elsewhere) means the card is showing stale state.
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.byUser(targetUserId) })
    },
  })
}

export function useSyncLockConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ lockEntityId, req, dryRun }: { lockEntityId: string; req: LockConfigSyncRequest; dryRun?: boolean }) =>
      locksService.syncConfig(lockEntityId, req, { dryRun }),
    onSuccess: async (data: LockConfigSyncResult, variables) => {
      // Only invalidate queries if this was a real sync (not dry-run)
      if (!data.dryRun) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.byUser(variables.req.userId) })
      }
    },
  })
}
