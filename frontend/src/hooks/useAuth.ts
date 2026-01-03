import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Routes } from '@/lib/constants'
import type { LoginCredentials, User } from '@/types'
import {
  useAuthSessionQuery,
  useCurrentUserQuery,
  useLoginMutation,
  useLogoutMutation,
  useVerify2FAMutation,
} from '@/hooks/useAuthQueries'
import { getErrorMessage } from '@/types/errors'

export function useAuth() {
  const sessionQuery = useAuthSessionQuery()
  const currentUserQuery = useCurrentUserQuery()
  const loginMutation = useLoginMutation()
  const logoutMutation = useLogoutMutation()
  const verify2FAMutation = useVerify2FAMutation()

  const user: User | null = currentUserQuery.data ?? null
  const isAuthenticated = sessionQuery.data.isAuthenticated
  const isLoading =
    currentUserQuery.isLoading || loginMutation.isPending || logoutMutation.isPending || verify2FAMutation.isPending

  const error = useMemo(() => {
    const errors: Array<unknown> = [
      currentUserQuery.error,
      loginMutation.error,
      logoutMutation.error,
      verify2FAMutation.error,
    ]
    for (const err of errors) {
      if (err) {
        const message = getErrorMessage(err, '')
        if (message) return message
      }
    }
    return null
  }, [currentUserQuery.error, loginMutation.error, logoutMutation.error, verify2FAMutation.error])

  const clearError = () => {
    loginMutation.reset()
    logoutMutation.reset()
    verify2FAMutation.reset()
  }

  return {
    user,
    isAuthenticated,
    isLoading,
    error,
    login: async (credentials: LoginCredentials) => {
      await loginMutation.mutateAsync(credentials)
    },
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
    verify2FA: async (code: string) => {
      await verify2FAMutation.mutateAsync(code)
    },
    fetchCurrentUser: async () => {
      await currentUserQuery.refetch()
    },
    clearError,
  }
}

export function useRequireAuth(redirectTo: string = Routes.LOGIN) {
  const { isAuthenticated, isLoading, fetchCurrentUser } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    fetchCurrentUser()
  }, [fetchCurrentUser])

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      navigate(redirectTo)
    }
  }, [isAuthenticated, isLoading, navigate, redirectTo])

  return { isAuthenticated, isLoading }
}

export function useLogin() {
  const { login, isLoading, error, clearError } = useAuth()
  const navigate = useNavigate()

  const handleLogin = async (credentials: LoginCredentials) => {
    try {
      await login(credentials)
      navigate(Routes.HOME)
    } catch (err) {
      if (err instanceof Error && err.message === '2FA_REQUIRED') {
        // Handle 2FA flow
        return { requires2FA: true }
      }
      throw err
    }
    return { requires2FA: false }
  }

  return {
    login: handleLogin,
    isLoading,
    error,
    clearError,
  }
}

export default useAuth
