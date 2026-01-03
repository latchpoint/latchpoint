import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import {
  useCurrentUserQuery,
  useLoginMutation,
  useVerify2FAMutation,
  useLogoutMutation,
} from '@/hooks/useAuthQueries'
import { queryKeys } from '@/types'

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useAuthQueries', () => {
  it('useCurrentUserQuery sets auth session true on success', async () => {
    const queryClient = createTestQueryClient()

    server.use(
      http.get('/api/users/me/', () => {
        return HttpResponse.json({
          data: { id: 'u1', email: 'a@example.com', display_name: 'A', role: 'admin' },
        })
      })
    )

    const { result } = renderHook(() => useCurrentUserQuery(), { wrapper: wrap(queryClient) })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(queryClient.getQueryData(queryKeys.auth.session)).toEqual({ isAuthenticated: true })
    expect(result.current.data).toMatchObject({ id: 'u1' })
  })

  it('useCurrentUserQuery returns null and sets session false on 401', async () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: true })

    server.use(
      http.get('/api/users/me/', () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      })
    )

    const { result } = renderHook(() => useCurrentUserQuery(), { wrapper: wrap(queryClient) })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBeNull()
    expect(queryClient.getQueryData(queryKeys.auth.session)).toEqual({ isAuthenticated: false })
  })

  it('useLoginMutation sets session + current user on success', async () => {
    const queryClient = createTestQueryClient()

    server.use(
      http.post('/api/auth/login/', () => {
        return HttpResponse.json({
          data: {
            requires_2fa: false,
            user: { id: 'u1', email: 'a@example.com', display_name: 'A', role: 'user' },
          },
        })
      })
    )

    const { result } = renderHook(() => useLoginMutation(), { wrapper: wrap(queryClient) })

    await result.current.mutateAsync({ email: 'a@example.com', password: 'pw' })

    expect(queryClient.getQueryData(queryKeys.auth.session)).toEqual({ isAuthenticated: true })
    expect(queryClient.getQueryData(queryKeys.auth.currentUser)).toMatchObject({ id: 'u1' })
  })

  it('useLoginMutation rejects with 2FA_REQUIRED without setting session true', async () => {
    const queryClient = createTestQueryClient()

    server.use(
      http.post('/api/auth/login/', () => {
        return HttpResponse.json({
          data: {
            requires_2fa: true,
            user: { id: 'u1', email: 'a@example.com', display_name: 'A', role: 'user' },
          },
        })
      })
    )

    const { result } = renderHook(() => useLoginMutation(), { wrapper: wrap(queryClient) })

    await expect(
      result.current.mutateAsync({ email: 'a@example.com', password: 'pw' })
    ).rejects.toMatchObject({ message: '2FA_REQUIRED' })

    expect(queryClient.getQueryData(queryKeys.auth.session)).not.toEqual({ isAuthenticated: true })
  })

  it('useVerify2FAMutation sets session + current user on success', async () => {
    const queryClient = createTestQueryClient()

    server.use(
      http.post('/api/auth/2fa/verify/', () => {
        return HttpResponse.json({
          data: {
            requires_2fa: false,
            user: { id: 'u2', email: 'b@example.com', display_name: 'B', role: 'user' },
          },
        })
      })
    )

    const { result } = renderHook(() => useVerify2FAMutation(), { wrapper: wrap(queryClient) })

    await result.current.mutateAsync('123456')

    expect(queryClient.getQueryData(queryKeys.auth.session)).toEqual({ isAuthenticated: true })
    expect(queryClient.getQueryData(queryKeys.auth.currentUser)).toMatchObject({ id: 'u2' })
  })

  it('useLogoutMutation clears session + current user and invalidates all queries', async () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: true })
    queryClient.setQueryData(queryKeys.auth.currentUser, { id: 'u1' })

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    server.use(
      http.post('/api/auth/logout/', () => {
        return HttpResponse.json({ data: null })
      })
    )

    const { result } = renderHook(() => useLogoutMutation(), { wrapper: wrap(queryClient) })

    await result.current.mutateAsync()

    expect(queryClient.getQueryData(queryKeys.auth.session)).toEqual({ isAuthenticated: false })
    expect(queryClient.getQueryData(queryKeys.auth.currentUser)).toBeNull()
    expect(invalidateSpy).toHaveBeenCalled()
  })
})

