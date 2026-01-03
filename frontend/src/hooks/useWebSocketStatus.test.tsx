import React, { type PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import { useWebSocketStatus } from '@/hooks/useWebSocketStatus'

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
}

describe('useWebSocketStatus', () => {
  it('returns initial disconnected and does not fetch (enabled=false)', () => {
    const queryClient = createTestQueryClient()
    function Wrapper({ children }: PropsWithChildren) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

    const { result } = renderHook(() => useWebSocketStatus(), { wrapper: Wrapper })
    expect(result.current.data).toBe('disconnected')
    expect(result.current.isFetching).toBe(false)
  })
})

