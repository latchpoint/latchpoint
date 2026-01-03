import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useZwavejsSettingsModel } from '@/features/zwavejs/hooks/useZwavejsSettingsModel'

const updateZ = vi.fn().mockResolvedValue({ ok: true })

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
    useUpdateZwavejsSettingsMutation: () => ({ isPending: false, mutateAsync: updateZ }),
    useTestZwavejsConnectionMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ notice: 'ok' }) }),
  }
})

describe('useZwavejsSettingsModel', () => {
  it('validates wsUrl when enabled', async () => {
    const { result } = renderHook(() => useZwavejsSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    act(() => {
      result.current.setDraft((prev) => (prev ? { ...prev, enabled: true, wsUrl: 'http://nope' } : prev))
    })

    await act(async () => {
      await result.current.save()
    })

    expect(result.current.error).toBe('WebSocket URL must start with ws:// or wss://.')
    expect(updateZ).not.toHaveBeenCalled()
  })
})

