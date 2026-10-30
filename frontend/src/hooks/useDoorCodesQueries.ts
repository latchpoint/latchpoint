import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
 * Whether the scheduler is still working on `code`, matching what
 * push_pending_door_codes retries: a slot it still has to clear (#151), or an
 * active code with a lock still waiting on its `set` or schedule, even when the
 * code is failed because another of its locks is (#126). A failed code with no
 * lock left waiting isn't, since only a Retry moves it. Nor is a
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
  return useQuery<DoorCode[]>({
    queryKey: queryKeys.doorCodes.byUser(userId),
    queryFn: () => doorCodesService.getDoorCodes(isAdmin ? { userId } : undefined),
    enabled: !!userId,
    // Nothing pushes door code changes to the page (#156), so pick up changes
    // made in another tab or by the scheduler when the tab becomes visible
    // again (TanStack listens for visibilitychange), even inside the default
    // staleTime, and keep checking while a code is still settling.
    refetchOnWindowFocus: 'always',
    refetchInterval: (query) => (query.state.data?.some(isDoorCodeSettling) ? DOOR_CODES_SETTLING_POLL_MS : false),
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
