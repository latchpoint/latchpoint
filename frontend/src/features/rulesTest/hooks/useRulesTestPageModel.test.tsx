import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act } from '@testing-library/react'
import { useRulesTestPageModel } from '@/features/rulesTest/hooks/useRulesTestPageModel'
import { queryKeys } from '@/types'

const simulate = vi.fn().mockResolvedValue({ rulesRan: 0 })

vi.mock('@/services', () => {
  return {
    rulesService: {
      simulate: (payload: any) => simulate(payload),
    },
  }
})

vi.mock('@/hooks/useRulesQueries', () => {
  return {
    useEntitiesQuery: () => ({
      data: [{ id: 1, entityId: 'binary_sensor.front_door', name: 'Front Door', domain: 'binary_sensor', source: 'home_assistant', lastState: 'off' }],
      isLoading: false,
      isFetching: false,
      error: null,
    }),
    useSyncEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'ok' }) }),
  }
})

vi.mock('@/hooks/useZwavejs', () => {
  return { useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'ok' }) }) }
})

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

describe('useRulesTestPageModel', () => {
  it('validates assumeForSeconds and avoids simulate call', async () => {
    const client = createClient()
    const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>

    const { result } = renderHook(() => useRulesTestPageModel(), { wrapper })

    act(() => {
      result.current.setAssumeForSeconds('nope')
    })

    await act(async () => {
      await result.current.simulate()
    })

    expect(simulate).not.toHaveBeenCalled()
    expect(result.current.displayedError).toBe('Assume-for seconds must be a number.')
  })

  it('refreshEntities invalidates entity query', () => {
    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>

    const { result } = renderHook(() => useRulesTestPageModel(), { wrapper })

    act(() => {
      result.current.refreshEntities()
    })

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.entities.all })
  })
})

