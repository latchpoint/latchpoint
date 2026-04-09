import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useFrigateSettingsModel } from '@/features/frigate/hooks/useFrigateSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useFrigate', () => {
  return {
    useFrigateStatusQuery: () => ({ data: { mqtt: { enabled: true, configured: true, connected: true } }, refetch: vi.fn() }),
    useFrigateSettingsQuery: () => ({
      data: {
        enabled: true,
        eventsTopic: 'frigate/events',
        retentionSeconds: 3600,
      },
      isLoading: false,
      refetch: vi.fn(),
    }),
    useFrigateDetectionsQuery: () => ({ data: [], refetch: vi.fn() }),
  }
})

describe('useFrigateSettingsModel', () => {
  it('returns read-only settings from query data', () => {
    const { result } = renderHook(() => useFrigateSettingsModel())

    expect(result.current.settings).toEqual({
      enabled: true,
      eventsTopic: 'frigate/events',
      retentionSeconds: 3600,
    })
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.mqttReady).toBe(true)
  })
})
