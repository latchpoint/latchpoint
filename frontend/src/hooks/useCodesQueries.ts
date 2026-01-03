import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { codesService, usersService } from '@/services'
import { queryKeys } from '@/types'
import type { CreateCodeRequest, UpdateCodeRequest, User } from '@/types'

export function useUsersQuery(enabled: boolean) {
  return useQuery<User[]>({
    queryKey: queryKeys.users.all,
    queryFn: usersService.listUsers,
    enabled,
  })
}

export function useCodesQuery(params: { userId: string; isAdmin: boolean }) {
  const { userId, isAdmin } = params
  return useQuery({
    queryKey: queryKeys.codes.byUser(userId),
    queryFn: () => codesService.getCodes(isAdmin ? { userId } : undefined),
    enabled: !!userId,
  })
}

export function useCreateCodeMutation(targetUserId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (req: CreateCodeRequest) => codesService.createCode(req),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.codes.byUser(targetUserId) })
    },
  })
}

export function useUpdateCodeMutation(targetUserId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, req }: { id: number; req: UpdateCodeRequest }) => codesService.updateCode(id, req),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.codes.byUser(targetUserId) })
    },
  })
}

