import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { useAlarmActions } from '@/hooks/useAlarmActions'
import { queryKeys } from '@/types'

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

describe('useAlarmActions', () => {
  beforeEach(() => {
    document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  })

  it('arms and updates alarm state cache, invalidating recent events', async () => {
    const queryClient = createTestQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    let receivedBody: unknown = null

    server.use(
      http.post('/api/alarm/arm/', async ({ request }) => {
        receivedBody = await request.json()
        return HttpResponse.json({
          data: {
            id: 1,
            current_state: 'armed_home',
            previous_state: 'disarmed',
            settings_profile: 1,
            entered_at: '2025-01-01T00:00:00Z',
            exit_at: null,
            last_transition_reason: 'test',
            last_transition_by: null,
            target_armed_state: 'armed_home',
            timing_snapshot: { delay_time: 0, arming_time: 0, trigger_time: 0 },
          },
        })
      })
    )

    function Wrapper({ children }: PropsWithChildren) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

    const { result } = renderHook(() => useAlarmActions(), { wrapper: Wrapper })

    await result.current.armHome('1234')

    expect(receivedBody).toMatchObject({ target_state: 'armed_home', code: '1234' })

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKeys.alarm.state)).toMatchObject({
        currentState: 'armed_home',
        previousState: 'disarmed',
      })
    })

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.events.recent })
  })

  it('disarms and clears countdown cache', async () => {
    const queryClient = createTestQueryClient()
    queryClient.setQueryData(queryKeys.alarm.countdown, { remainingSeconds: 10 })

    server.use(
      http.post('/api/alarm/disarm/', () => {
        return HttpResponse.json({
          data: {
            id: 1,
            current_state: 'disarmed',
            previous_state: 'armed_home',
            settings_profile: 1,
            entered_at: '2025-01-01T00:00:00Z',
            exit_at: null,
            last_transition_reason: 'test',
            last_transition_by: null,
            target_armed_state: null,
            timing_snapshot: { delay_time: 0, arming_time: 0, trigger_time: 0 },
          },
        })
      })
    )

    function Wrapper({ children }: PropsWithChildren) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

    const { result } = renderHook(() => useAlarmActions(), { wrapper: Wrapper })

    await result.current.disarm('1234')

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKeys.alarm.countdown)).toBeNull()
      expect(queryClient.getQueryData(queryKeys.alarm.state)).toMatchObject({
        currentState: 'disarmed',
      })
    })
  })
})

