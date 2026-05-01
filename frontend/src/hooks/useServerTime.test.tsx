import React, { type PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { useServerTimeQuery } from '@/hooks/useServerTime'

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useServerTimeQuery', () => {
  it('fetches /api/system/time/ and exposes the parsed payload', async () => {
    server.use(
      http.get('/api/system/time/', () =>
        HttpResponse.json({
          data: {
            timestamp: '2026-04-30T18:42:31+00:00',
            timezone: 'America/Los_Angeles',
            epoch_ms: 1745001751000,
            formatted: '2026-04-30 11:42:31 PDT',
          },
        })
      )
    )

    const client = createClient()
    const { result } = renderHook(() => useServerTimeQuery(), { wrapper: wrap(client) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({
      timestamp: '2026-04-30T18:42:31+00:00',
      timezone: 'America/Los_Angeles',
      epochMs: 1745001751000,
      formatted: '2026-04-30 11:42:31 PDT',
    })
  })
})
