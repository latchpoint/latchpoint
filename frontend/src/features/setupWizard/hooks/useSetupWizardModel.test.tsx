import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { renderHook, act } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { useSetupWizardModel } from '@/features/setupWizard/hooks/useSetupWizardModel'
import { queryKeys } from '@/types'
import { UserRole } from '@/lib/constants'

let mockUser: any | null = null

vi.mock('@/hooks/useAuth', () => {
  return {
    useAuth: () => ({
      user: mockUser,
      logout: vi.fn().mockResolvedValue(undefined),
    }),
  }
})

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <MemoryRouter initialEntries={['/setup']}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MemoryRouter>
    )
  }
}

function makeUser(role: string) {
  return {
    id: 'user-1',
    email: 'admin@example.com',
    displayName: 'Admin',
    role,
    isActive: true,
    has2FA: false,
    createdAt: '2026-01-01T00:00:00Z',
    lastLogin: null,
  }
}

describe('useSetupWizardModel', () => {
  it('sets error when not authenticated', async () => {
    mockUser = null
    const queryClient = createTestQueryClient()
    const onSuccess = vi.fn()

    const { result } = renderHook(() => useSetupWizardModel({ onSuccess }), {
      wrapper: createWrapper(queryClient),
    })

    await act(async () => {
      await result.current.onSubmit({ label: 'Admin', code: '1234', reauthPassword: 'password' })
    })

    expect(result.current.error).toBe('Not authenticated.')
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('sets error when user is not admin', async () => {
    mockUser = makeUser(UserRole.RESIDENT)
    const queryClient = createTestQueryClient()
    const onSuccess = vi.fn()

    const { result } = renderHook(() => useSetupWizardModel({ onSuccess }), {
      wrapper: createWrapper(queryClient),
    })

    await act(async () => {
      await result.current.onSubmit({ label: 'Resident', code: '1234', reauthPassword: 'password' })
    })

    expect(result.current.error).toBe('An admin must create your alarm code.')
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('creates code, invalidates setup-status query, and calls onSuccess', async () => {
    mockUser = makeUser(UserRole.ADMIN)
    const queryClient = createTestQueryClient()
    const onSuccess = vi.fn()

    queryClient.setQueryData(queryKeys.onboarding.setupStatus, { setupRequired: true })

    let receivedBody: any = null
    server.use(
      http.post('/api/codes/', async ({ request }) => {
        receivedBody = await request.json()
        return HttpResponse.json({ data: { id: 1 } })
      })
    )

    const { result } = renderHook(() => useSetupWizardModel({ onSuccess }), {
      wrapper: createWrapper(queryClient),
    })

    await act(async () => {
      await result.current.onSubmit({ label: 'Admin', code: '1234', reauthPassword: 'password' })
    })

    expect(receivedBody).toMatchObject({
      user_id: 'user-1',
      code: '1234',
      label: 'Admin',
      reauth_password: 'password',
      allowed_states: expect.any(Array),
    })
    expect(onSuccess).toHaveBeenCalledTimes(1)

    const state = queryClient.getQueryState(queryKeys.onboarding.setupStatus)
    expect(state?.isInvalidated).toBe(true)
  })
})

