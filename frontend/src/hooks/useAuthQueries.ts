import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LoginCredentials, LoginResponse, User } from '@/types'
import type { ApiError } from '@/types'
import { authService } from '@/services'
import { queryKeys } from '@/types'
import { ONE_MINUTE_MS } from '@/lib/constants'

type AuthSession = {
  isAuthenticated: boolean
}

function isApiUnauthorized(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const maybe = error as ApiError
  return maybe.code === '401'
}

export function useAuthSessionQuery() {
  return useQuery<AuthSession>({
    queryKey: queryKeys.auth.session,
    queryFn: async () => ({ isAuthenticated: false }),
    initialData: { isAuthenticated: false },
    enabled: false,
  })
}

export function useCurrentUserQuery() {
  const queryClient = useQueryClient()

  const query = useQuery<User | null, ApiError>({
    queryKey: queryKeys.auth.currentUser,
    queryFn: async () => {
      try {
        const user = await authService.getCurrentUser()
        queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: true })
        return user
      } catch (error) {
        if (isApiUnauthorized(error)) {
          queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: false })
          return null
        }
        throw error
      }
    },
    enabled: true,
    retry: (failureCount) => failureCount < 1,
    staleTime: ONE_MINUTE_MS,
  })

  return query
}

export function useLoginMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (credentials: LoginCredentials): Promise<LoginResponse> => {
      const response = await authService.login(credentials)
      if (response.requires2FA) {
        throw new Error('2FA_REQUIRED')
      }
      return response
    },
    onSuccess: (response) => {
      queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: true })
      queryClient.setQueryData(queryKeys.auth.currentUser, response.user)
    },
    onError: (error) => {
      if (error instanceof Error && error.message === '2FA_REQUIRED') {
        // Keep session false until 2FA verify completes.
        return
      }
      queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: false })
      queryClient.removeQueries({ queryKey: queryKeys.auth.currentUser })
    },
  })
}

export function useVerify2FAMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => authService.verify2FA(code),
    onSuccess: (response) => {
      queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: true })
      queryClient.setQueryData(queryKeys.auth.currentUser, response.user)
    },
    onError: () => {
      // Do not clear tokens; backend may still consider login session pending.
    },
  })
}

export function useLogoutMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await authService.logout()
    },
    onSettled: async () => {
      queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: false })
      queryClient.setQueryData(queryKeys.auth.currentUser, null)
      await queryClient.invalidateQueries()
    },
  })
}
