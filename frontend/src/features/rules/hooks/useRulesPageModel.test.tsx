import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act } from '@testing-library/react'
import { useRulesPageModel } from '@/features/rules/hooks/useRulesPageModel'
import { queryKeys } from '@/types'

vi.mock('@/hooks/useRulesQueries', () => {
  return {
    useRulesQuery: () => ({ data: [], isLoading: false, error: null }),
    useEntitiesQuery: () => ({
      data: [
        { id: 1, entityId: 'binary_sensor.front_door', name: 'Front Door', domain: 'binary_sensor', source: 'home_assistant' },
        { id: 2, entityId: 'lock.front_door', name: 'Front Lock', domain: 'lock', source: 'home_assistant' },
      ],
      isLoading: false,
      error: null,
    }),
    useSyncEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'Synced.' }) }),
    useRunRulesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'Ran.' }) }),
    useSaveRuleMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'Saved.' }) }),
    useDeleteRuleMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'Deleted.' }) }),
  }
})

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'Synced zwave.' }) }),
  }
})

vi.mock('@/hooks/useFrigate', () => {
  return {
    useFrigateOptionsQuery: () => ({ isLoading: false, error: null, data: { cameras: [], zonesByCamera: {} } }),
  }
})

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

describe('useRulesPageModel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('derives entityIds from builder conditions', () => {
    const client = createClient()
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useRulesPageModel(), { wrapper })

    act(() => {
      result.current.setConditions([
        { id: 'c1', type: 'entity_state', entityId: 'binary_sensor.front_door', equals: 'on', negate: false },
        { id: 'c2', type: 'entity_state', entityId: 'binary_sensor.front_door', equals: 'off', negate: true },
        { id: 'c3', type: 'entity_state', entityId: 'lock.front_door', equals: 'locked', negate: false },
      ] as any)
    })

    expect(result.current.derivedEntityIds).toEqual(['binary_sensor.front_door', 'lock.front_door'])
    expect(result.current.derivedEntityIdsText).toContain('binary_sensor.front_door')
  })

  it('validates required name on submit', async () => {
    const client = createClient()
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useRulesPageModel(), { wrapper })

    await act(async () => {
      await result.current.onSubmit()
    })

    expect(result.current.displayedError).toBe('Rule name is required.')
  })

  it('validates JSON when advanced mode enabled', async () => {
    const client = createClient()
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useRulesPageModel(), { wrapper })

    act(() => {
      result.current.setName('My Rule')
      result.current.setAdvanced(true)
      result.current.setDefinitionText('{ not json }')
    })

    await act(async () => {
      await result.current.onSubmit()
    })

    expect(result.current.displayedError).toBe('Definition is not valid JSON.')
  })

  it('refresh invalidates rules and entities queries', () => {
    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useRulesPageModel(), { wrapper })

    act(() => {
      result.current.onRefresh()
    })

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.rules.all })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.entities.all })
  })
})

