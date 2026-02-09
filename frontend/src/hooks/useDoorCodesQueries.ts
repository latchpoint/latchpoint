import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { doorCodesService, locksService } from '@/services'
import { queryKeys } from '@/types'
import type { CreateDoorCodeRequest, DismissedAssignment, DoorCode, LockConfigSyncRequest, LockConfigSyncResult, UpdateDoorCodeRequest } from '@/types'

export function useDoorCodesQuery(params: { userId: string; isAdmin: boolean }) {
  const { userId, isAdmin } = params
  return useQuery<DoorCode[]>({
    queryKey: queryKeys.doorCodes.byUser(userId),
    queryFn: () => doorCodesService.getDoorCodes(isAdmin ? { userId } : undefined),
    enabled: !!userId,
  })
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
    onSuccess: async () => {
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

export function useDismissedAssignmentsQuery(lockEntityId: string) {
  return useQuery<DismissedAssignment[]>({
    queryKey: queryKeys.doorCodes.dismissedAssignments(lockEntityId),
    queryFn: () => locksService.getDismissedAssignments(lockEntityId),
    enabled: !!lockEntityId,
  })
}

export function useUndismissAssignmentMutation(lockEntityId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ assignmentId, reauthPassword }: { assignmentId: number; reauthPassword: string }) =>
      locksService.undismissAssignment(assignmentId, { reauthPassword }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.dismissedAssignments(lockEntityId) })
      // Also refresh door codes list since undismissing reactivates the code
      await queryClient.invalidateQueries({ queryKey: queryKeys.doorCodes.all })
    },
  })
}
