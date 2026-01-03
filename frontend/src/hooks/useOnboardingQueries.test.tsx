import React, { type PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { useSetupStatusQuery } from '@/hooks/useOnboardingQueries'
import { queryKeys } from '@/types'

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useOnboardingQueries', () => {
  it('does not fetch setup-status when not authenticated', async () => {
    const queryClient = createTestQueryClient()

    let calls = 0
    server.use(
      http.get('/api/onboarding/setup-status/', () => {
        calls += 1
        return HttpResponse.json({ data: { onboarding_required: false, setup_required: false, requirements: {} } })
      })
    )

    const { result } = renderHook(() => useSetupStatusQuery(), { wrapper: wrap(queryClient) })
    expect(result.current.isFetching).toBe(false)
    expect(calls).toBe(0)
  })

  it('fetches setup-status when authenticated', async () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(queryKeys.auth.session, { isAuthenticated: true })

    let calls = 0
    server.use(
      http.get('/api/onboarding/setup-status/', () => {
        calls += 1
        return HttpResponse.json({
          data: {
            onboarding_required: false,
            setup_required: true,
            requirements: {
              has_active_settings_profile: true,
              has_alarm_snapshot: true,
              has_alarm_code: false,
              has_sensors: false,
              home_assistant_connected: false,
            },
          },
        })
      })
    )

    const { result } = renderHook(() => useSetupStatusQuery(), { wrapper: wrap(queryClient) })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(calls).toBe(1)
    expect(result.current.data?.setupRequired).toBe(true)
  })
})

