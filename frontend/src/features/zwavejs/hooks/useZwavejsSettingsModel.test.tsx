import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useZwavejsSettingsModel } from '@/features/zwavejs/hooks/useZwavejsSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useZwavejsStatusQuery: () => ({ data: { enabled: true }, refetch: vi.fn() }),
    useZwavejsSettingsQuery: () => ({
      data: { enabled: false, wsUrl: '', connectTimeoutSeconds: 5, reconnectMinSeconds: 1, reconnectMaxSeconds: 30 },
      isLoading: false,
      refetch: vi.fn(),
    }),
    useUpdateZwavejsSettingsMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'ok' }) }),
  }
})

describe('useZwavejsSettingsModel', () => {
  it('provides read-only draft from settings query', async () => {
    const { result } = renderHook(() => useZwavejsSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.draft).toMatchObject({
      enabled: false,
      wsUrl: '',
      connectTimeoutSeconds: '5',
      reconnectMinSeconds: '1',
      reconnectMaxSeconds: '30',
    })
    expect(result.current.isAdmin).toBe(true)
  })
})
