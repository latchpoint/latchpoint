import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { doorCodesService, locksService } from '@/services'
import { queryKeys } from '@/types'
import type { CreateDoorCodeRequest, DoorCode, LockConfigSyncRequest, LockConfigSyncResult, UpdateDoorCodeRequest } from '@/types'

/** How often the door codes refetch while one is waiting on its locks. */
export const DOOR_CODES_SETTLING_POLL_MS = 15_000

/**
 * Whether the backend is still working on `code`: a push the scheduler will
 * retry, or a slot it still has to clear (#151). A failed code isn't, since the
 * scheduler gives up on those and only a Retry moves them.
 */
export function isDoorCodeSettling(code: DoorCode): boolean {
  if (code.pushState === 'failed') return false
  return (
    code.pushState === 'pending' ||
    (code.pendingSlotClears?.length ?? 0) > 0 ||
    (code.lockSlotAssignments ?? []).some((a) => a.pendingRemoval)
  )
}

export function useDoorCodesQuery(params: { userId: string; isAdmin: boolean }) {
  const { userId, isAdmin } = params
  return useQuery<DoorCode[]>({
    queryKey: queryKeys.doorCodes.byUser(userId),
    queryFn: () => doorCodesService.getDoorCodes(isAdmin ? { userId } : undefined),
    enabled: !!userId,
    // Nothing pushes door code changes to the page (#156), so pick up changes
    // made in another tab or by the scheduler when the window comes back, even
    // inside the default staleTime, and keep checking while a code is still
    // settling.
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
