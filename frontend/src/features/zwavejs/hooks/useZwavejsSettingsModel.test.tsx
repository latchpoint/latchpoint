import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useZwavejsSettingsModel } from '@/features/zwavejs/hooks/useZwavejsSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useZwavejsStatusQuery: () => ({ data: { enabled: true }, refetch: vi.fn() }),
    useZwavejsSettingsQuery: () => ({
      data: { enabled: true, wsUrl: 'ws://localhost:3000', connectTimeoutSeconds: 5, reconnectMinSeconds: 1, reconnectMaxSeconds: 30 },
      isLoading: false,
      refetch: vi.fn(),
    }),
    useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'ok' }) }),
  }
})

describe('useZwavejsSettingsModel', () => {
  it('returns read-only settings from query data', () => {
    const { result } = renderHook(() => useZwavejsSettingsModel())

    expect(result.current.settings).toEqual({
      enabled: true,
      wsUrl: 'ws://localhost:3000',
      connectTimeoutSeconds: 5,
      reconnectMinSeconds: 1,
      reconnectMaxSeconds: 30,
    })
    expect(result.current.isAdmin).toBe(true)
  })
})
